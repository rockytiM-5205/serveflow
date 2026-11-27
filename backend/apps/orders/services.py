"""Creating orders and recording payments. Prices always come from the database, never the client."""
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import record
from apps.platform_admin import usage
from apps.common.exceptions import Conflict
from apps.menu.models import MenuItem
from apps.restaurants import hours
from apps.restaurants.models import PaymentAccount, Restaurant

from apps.restaurants import push

from . import lateness
from .workflow import change_status
from .models import (
    ActorType, DailyOrderCounter, Fulfilment, Order, OrderItem, OrderSource, OrderStatus, OrderStatusEvent,
    Payment, PaymentStatus,
)

MAX_OPEN_ORDERS_PER_PHONE = 3
MAX_QUANTITY_PER_ITEM = 99


def business_date_for(restaurant):
    return timezone.now().astimezone(ZoneInfo(restaurant.timezone)).date()


def next_order_number(restaurant, business_date):
    """Next short code for the day. The counter row is locked until the order commits."""
    counter, _ = DailyOrderCounter.objects.select_for_update().get_or_create(
        restaurant=restaurant, business_date=business_date, defaults={"last_number": 0}
    )
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return counter.last_number


@transaction.atomic
def create_order(restaurant, data):
    """data: customer_name, customer_phone, fulfilment_type, table_number, notes, lines=[(menu_item_id, qty)], source."""
    restaurant = Restaurant.objects.get(pk=restaurant.pk)  # fresh switches, not the ones read earlier
    if not restaurant.accepting_orders:
        raise Conflict("This restaurant isn't taking orders right now.", code="not_accepting_orders")

    usage.assert_can_accept_orders(restaurant)  # raises ORDER_LIMIT_REACHED; checked against the database, never a cache
    account = PaymentAccount.objects.filter(restaurant=restaurant).first()
    if not (account and account.ready):  # customers pay before preparing starts, so there must be somewhere to pay
        raise Conflict("This restaurant can't take orders yet.", code="payment_details_missing")

    fulfilment = data["fulfilment_type"]
    allowed = {Fulfilment.PICKUP: restaurant.pickup_enabled, Fulfilment.DINE_IN: restaurant.dine_in_enabled}
    if not allowed[fulfilment]:
        raise Conflict("This restaurant doesn't offer that option.", code="fulfilment_disabled")
    now = timezone.now()
    pickup_at, pickup_fee = None, Decimal("0.00")
    late_policy, late_policy_accepted_at = None, None
    if fulfilment == Fulfilment.PICKUP:
        pickup_at = data.get("pickup_at")
        if pickup_at is None:
            raise ValidationError({"pickup_at": ["Choose when you will collect your order."]})
        problem = hours.pickup_problem(restaurant, pickup_at, now)
        if problem:
            raise ValidationError({"pickup_at": [problem]})
        pickup_fee = restaurant.pickup_fee
        if restaurant.late_fee_enabled:
            # The customer must have seen and accepted the rules; they are copied onto the order so they can't change afterwards.
            if not data.get("accept_late_policy"):
                raise ValidationError({"accept_late_policy": ["Please accept the late pickup policy to place a pickup order."]})
            late_policy, late_policy_accepted_at = lateness.snapshot(restaurant), now
    table_number = (data.get("table_number") or "").strip() or None
    if fulfilment == Fulfilment.DINE_IN:
        if restaurant.requires_table_number and not table_number:
            raise ValidationError({"table_number": ["Enter your table number."]})
    else:
        table_number = None

    quantities = {}
    for item_id, quantity in data["lines"]:
        quantities[item_id] = quantities.get(item_id, 0) + quantity
    if any(q > MAX_QUANTITY_PER_ITEM for q in quantities.values()):
        raise ValidationError({"items": [f"You can order at most {MAX_QUANTITY_PER_ITEM} of one item."]})

    open_orders = Order.objects.filter(
        restaurant=restaurant, customer_phone=data["customer_phone"], status=OrderStatus.PENDING
    ).count()
    if open_orders >= MAX_OPEN_ORDERS_PER_PHONE:
        raise Conflict("You already have several orders waiting. Please wait for the restaurant to respond.", code="too_many_open_orders")

    orderable = {
        item.pk: item
        for item in MenuItem.objects.filter(
            restaurant=restaurant, pk__in=list(quantities), archived_at__isnull=True, category__is_active=True
        )
    }
    problems = []
    for item_id in quantities:
        item = orderable.get(item_id)
        if item is None:
            problems.append({"id": item_id, "reason": "not_found"})  # also covers other restaurants' items
        elif not item.is_available:
            problems.append({"id": item_id, "name": item.name, "reason": "unavailable"})
    if problems:
        raise Conflict("Some items can't be ordered any more.", code="item_unavailable", details={"items": problems})

    lines, subtotal = [], Decimal("0.00")
    for item_id, quantity in quantities.items():
        item = orderable[item_id]
        line_total = (item.price * quantity).quantize(Decimal("0.01"))
        subtotal += line_total
        lines.append((item, quantity, line_total))

    business_date = business_date_for(restaurant)
    order = Order.objects.create(
        restaurant=restaurant, business_date=business_date, order_number=next_order_number(restaurant, business_date),
        fulfilment_type=fulfilment, table_number=table_number, customer_name=data["customer_name"],
        customer_phone=data["customer_phone"], notes=data.get("notes", ""), currency=restaurant.currency,
        subtotal=subtotal, total=subtotal + pickup_fee, pickup_at=pickup_at, pickup_fee=pickup_fee,
        late_policy=late_policy, late_policy_accepted_at=late_policy_accepted_at, customer=data.get("customer"), source=data.get("source") or OrderSource.MARKETPLACE,
    )
    OrderItem.objects.bulk_create(
        OrderItem(
            order=order, restaurant=restaurant, menu_item=item, item_name=item.name, unit_name=item.unit_name,
            unit_price=item.price, quantity=quantity, line_total=line_total,
        )
        for item, quantity, line_total in lines
    )
    OrderStatusEvent.objects.create(
        order=order, restaurant=restaurant, from_status=None, to_status=OrderStatus.PENDING, actor_type=ActorType.CUSTOMER
    )
    transaction.on_commit(lambda: push.notify_new_order(restaurant.pk, order.reference, sum(quantity for _item, quantity, _total in lines)))
    if restaurant.auto_accept_orders:  # a busy restaurant doesn't press Accept on every order; paying is still needed before preparing
        order = change_status(order=order, to_status=OrderStatus.CONFIRMED, actor_type=ActorType.SYSTEM, reason="Accepted automatically")
    return order


def record_payment(*, order, actor_user, method, amount, reference=""):
    """Confirm that the customer's full payment arrived (staff checked the bank or took cash). One payment per order; the amount
    must equal the total. Allowed until the order is rejected or cancelled; preparing can't start before this."""
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.payment_status == PaymentStatus.PAID:
            raise Conflict("This order is already paid.", code="already_paid")
        if locked.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED):
            raise Conflict(
                "This order was rejected or cancelled, so it can't be paid.", code="not_payable", details={"status": locked.status}
            )
        if amount != locked.total:
            raise ValidationError({"amount": [f"The amount must equal the order total ({locked.total})."]})
        usage.assert_can_commit_payment(locked.restaurant)  # a paid order will complete and be counted, so it must fit the allowance
        Payment.objects.create(
            order=locked, restaurant=locked.restaurant, amount=amount, currency=locked.currency, method=method,
            reference=reference, recorded_by=actor_user,
        )
        locked.payment_status = PaymentStatus.PAID
        locked.save(update_fields=["payment_status", "updated_at"])
        record(
            restaurant=locked.restaurant, actor=actor_user, action="payment.recorded", entity_type="order",
            entity_id=locked.pk, metadata={"code": locked.code, "amount": str(amount), "method": method},
        )
    return locked


def claim_payment(order):
    """The customer says they have paid. This only flags the order for staff to check the bank; it never marks it paid and
    never starts preparing. Saying it twice is harmless."""
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.payment_status in (PaymentStatus.CLAIMED, PaymentStatus.PAID):
            return locked
        if locked.status not in (OrderStatus.PENDING, OrderStatus.CONFIRMED):
            raise Conflict("This order can't be paid any more.", code="not_payable", details={"status": locked.status})
        locked.payment_status = PaymentStatus.CLAIMED
        locked.payment_claimed_at = timezone.now()
        locked.save(update_fields=["payment_status", "payment_claimed_at", "updated_at"])
        record(
            restaurant=locked.restaurant, actor=None, action="payment.claimed", entity_type="order",
            entity_id=locked.pk, metadata={"code": locked.code},
        )
    return locked
