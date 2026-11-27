"""Completed-order billing: periods, the usage ledger, allowance and order-pack capacity.

The rules, in one place:

* The billable event is an order becoming COMPLETED. Nothing else is counted (views, carts, rejected, cancelled or
  duplicate requests never reach the ledger).
* Usage is counted in explicit BillingPeriods. A period carries a frozen copy of the plan's terms, so editing a plan
  never changes a period that already exists. Periods follow the subscription's anniversary, not the calendar month.
* A period's capacity is its included allowance plus any ACTIVE order packs bought for that period. Packs expire with the
  period; unused capacity never rolls over.
* New orders are refused (ORDER_LIMIT_REACHED) once completed orders PLUS orders already paid and still in progress reach the
  capacity. Those paid-in-progress orders are "committed": they will complete and be counted, so they reserve a slot. Marking an
  order paid is refused the same way, which is what stops anyone queueing orders below the limit and finishing them all beyond it.
  Unpaid orders reserve nothing (otherwise anyone could fill a restaurant's allowance with fake orders). The only way to exceed the
  allowance is an order that was already paid when the allowance ran out; it is recorded as OVERAGE so counts stay truthful and
  nobody is stuck mid-service.
* Everything here reads the database. The 30-second lock cache in locks.py is never trusted for billing decisions.
"""
import calendar
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, F
from django.utils import timezone

from apps.common.exceptions import Conflict

from . import locks
from .models import BillingPeriod, OrderPack, OrderUsage, Plan, Subscription

WARNING_LEVELS = (100, 90, 75)


class OrderLimitReached(Conflict):
    """402 with the stable code ORDER_LIMIT_REACHED."""

    status_code = 402

    def __init__(self, period, remaining_info):
        super().__init__(
            "This restaurant has reached its order limit for the current billing period. The restaurant needs to upgrade "
            "its plan or buy additional order capacity before it can accept new orders.",
            code="ORDER_LIMIT_REACHED",
            details={"action": "upgrade_or_purchase_order_pack", "resets_at": period.ends_at.isoformat(), **remaining_info},
        )


class SubscriptionInactive(Conflict):
    status_code = 402

    def __init__(self):
        super().__init__(
            "This restaurant isn't taking orders through ServeFlow right now.", code="subscription_inactive", details={}
        )


# ---------------------------------------------------------------- period arithmetic
def add_months(moment, months):
    """`moment` plus whole months, landing on the last day of a shorter month (Jan 31 + 1 month = Feb 28/29)."""
    index = moment.month - 1 + months
    year, month = moment.year + index // 12, index % 12 + 1
    return moment.replace(year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1]))


def interval_months(interval):
    return 12 if interval == Plan.Interval.YEARLY else 1


def months_between(earlier, later):
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def period_end(anchor, start, interval):
    """End of the period that begins at `start`. Always measured from the anchor, so the 31st comes back after February."""
    return add_months(anchor, months_between(anchor, start) + interval_months(interval))


def grace():
    return timedelta(days=getattr(settings, "BILLING_GRACE_DAYS", 3))


# ---------------------------------------------------------------- periods
def open_period(subscription, plan, starts_at, ends_at):
    """Record a billing period with the plan's terms frozen as they are right now."""
    period, _ = BillingPeriod.objects.get_or_create(
        subscription=subscription, starts_at=starts_at,
        defaults={
            "restaurant_id": subscription.restaurant_id, "plan": plan, "plan_name": plan.name, "price": plan.price,
            "currency": plan.currency, "included_orders": plan.included_orders,
            "rate_limit_per_minute": plan.rate_limit_per_minute, "ends_at": ends_at,
        },
    )
    return period


def start_paid_period(subscription, plan, now):
    """Open the period a confirmed payment buys, and update the subscription's dates to match. Returns the new period.

    Paying while still inside a paid period renews seamlessly: the new period starts when the current one ends and keeps
    the same anchor day. Paying first time, after a trial, or after a lapse starts a fresh period now, and `now` becomes
    the anchor (usage resets then). A period still running at that moment is closed early so periods never overlap.
    """
    early = (
        subscription.status == Subscription.Status.ACTIVE and subscription.current_period_end > now
        and subscription.billing_anchor is not None
    )
    if early:
        start, anchor = subscription.current_period_end, subscription.billing_anchor
    else:
        start, anchor = now, now
        BillingPeriod.objects.filter(subscription=subscription, starts_at__lt=now, ends_at__gt=now).update(ends_at=now)
    end = period_end(anchor, start, plan.interval)
    period = open_period(subscription, plan, start, end)
    subscription.billing_anchor = anchor
    subscription.current_period_start, subscription.current_period_end = start, end
    return period


def current_period(subscription, now=None):
    """The period that covers `now`, else (inside the grace window after a lapse) the last one, else None."""
    now = now or timezone.now()
    periods = BillingPeriod.objects.filter(subscription=subscription)
    period = periods.filter(starts_at__lte=now, ends_at__gt=now).order_by("-starts_at").first()
    if period:
        return period
    last = periods.order_by("-ends_at").first()
    if last is None:  # a subscription from before periods existed: derive its period from its own dates, once
        return _legacy_period(subscription, now)
    in_grace = subscription.status in (Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE) and last.ends_at <= now < last.ends_at + grace()
    return last if in_grace else None


def latest_period(subscription):
    return BillingPeriod.objects.filter(subscription=subscription).order_by("-ends_at").first() or _legacy_period(subscription, None)


def _legacy_period(subscription, now):
    if subscription.current_period_end <= subscription.current_period_start:
        return None
    period = open_period(subscription, subscription.plan, subscription.current_period_start, subscription.current_period_end)
    if now is None or period.starts_at <= now < period.ends_at:
        return period
    return None


# ---------------------------------------------------------------- capacity
def capacity(period, now=None):
    """Counts for one period, straight from the ledger. `remaining` never goes below zero."""
    now = now or timezone.now()
    rows = OrderUsage.objects.filter(billing_period=period)
    used = rows.count()
    plan_used = rows.filter(charged_to=OrderUsage.ChargedTo.PLAN).count()
    pack_used = rows.filter(charged_to=OrderUsage.ChargedTo.PACK).count()
    packs_live = now < period.ends_at  # a pack expires with its period
    pack_total = sum(OrderPack.objects.filter(billing_period=period, status=OrderPack.Status.ACTIVE).values_list("orders", flat=True)) if packs_live else 0
    total = period.included_orders + pack_total
    remaining = max(period.included_orders - plan_used, 0) + max(pack_total - pack_used, 0)
    percent = 100 if total == 0 or used >= total else int(used * 100 / total)
    return {
        "included": period.included_orders, "extra": pack_total, "capacity": total, "used": used, "remaining": remaining,
        "percent": percent, "warning": next((level for level in WARNING_LEVELS if percent >= level), None),
        "plan_used": plan_used, "pack_used": pack_used,
    }


def summary(subscription, now=None):
    """What the billing dashboard shows, or None when there is no subscription or no period yet."""
    now = now or timezone.now()
    period = current_period(subscription, now)
    if period is None:
        return None
    cap = capacity(period, now)
    return {
        "period_start": period.starts_at, "period_end": period.ends_at, "plan_name": period.plan_name,
        "included_orders": cap["included"], "extra_capacity": cap["extra"], "completed_orders": cap["used"],
        "remaining": cap["remaining"], "percent_used": cap["percent"], "warning_level": cap["warning"],
        "limit_reached": cap["remaining"] <= 0,
    }


# ---------------------------------------------------------------- enforcement
def committed_open_orders(restaurant_id) -> int:
    """Orders that are paid and not finished: they will become COMPLETED, so each one already holds a slot of the allowance."""
    from apps.orders.models import Order, OrderStatus, PaymentStatus

    return Order.objects.filter(
        restaurant_id=restaurant_id, payment_status=PaymentStatus.PAID,
        status__in=[OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.SERVING, OrderStatus.READY_FOR_PICKUP],
    ).count()


def _locked_subscription(restaurant):
    qs = Subscription.objects.select_related("plan").filter(restaurant_id=restaurant.pk)
    if connection.in_atomic_block:  # serialise concurrent checks for one restaurant behind the subscription row
        qs = qs.select_for_update(of=("self",))
    return qs.first()


def _assert_slot_free(sub, period, now):
    cap = capacity(period, now)
    committed = committed_open_orders(sub.restaurant_id)
    if cap["remaining"] - committed <= 0:
        raise OrderLimitReached(period, {"allowance": cap["capacity"], "completed_orders": cap["used"], "paid_in_progress": committed})


def assert_can_accept_orders(restaurant, now=None):
    """Raise unless this restaurant may accept a NEW order right now. Restaurants without a subscription are not limited."""
    if not getattr(settings, "PLATFORM_ENFORCE_ORDER_LIMITS", True):
        return
    now = now or timezone.now()
    sub = _locked_subscription(restaurant)
    if sub is None:
        return
    if getattr(settings, "PLATFORM_ENFORCE_SUBSCRIPTIONS", True) and locks.is_locked(sub.status, sub.current_period_end, now):
        raise SubscriptionInactive()
    period = current_period(sub, now)
    if period is None:
        raise SubscriptionInactive()
    _assert_slot_free(sub, period, now)


def assert_can_commit_payment(restaurant, now=None):
    """Raise ORDER_LIMIT_REACHED when marking one more order paid would put paid orders beyond the allowance. Called when staff
    confirm a payment. No subscription, or no current period, means no limit here (the lock checks live elsewhere)."""
    if not getattr(settings, "PLATFORM_ENFORCE_ORDER_LIMITS", True):
        return
    now = now or timezone.now()
    sub = _locked_subscription(restaurant)
    if sub is None:
        return
    period = current_period(sub, now)
    if period is None:
        return
    _assert_slot_free(sub, period, now)


# ---------------------------------------------------------------- the ledger
def record_completion(order, now=None):
    """Count a completed order exactly once. Returns (usage_row, created); (None, False) when the restaurant has no subscription.

    The subscription row is locked, so two orders completing at the same moment are counted one after the other and
    each sees the other's row. The (order, event) unique constraint is the backstop if this ever runs twice.
    """
    now = now or timezone.now()
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().select_related("plan").filter(restaurant_id=order.restaurant_id).first()
        if sub is None:
            return None, False
        existing = OrderUsage.objects.filter(order=order, event_type=OrderUsage.Event.ORDER_COMPLETED).first()
        if existing:
            return existing, False
        period = current_period(sub, now) or latest_period(sub)
        if period is None:
            return None, False  # no period was ever recorded; nothing to attribute the order to
        cap = capacity(period, now)
        charged_to, pack = OrderUsage.ChargedTo.OVERAGE, None
        if cap["plan_used"] < period.included_orders:
            charged_to = OrderUsage.ChargedTo.PLAN
        elif now < period.ends_at:
            pack = (
                OrderPack.objects.filter(billing_period=period, status=OrderPack.Status.ACTIVE)
                .annotate(used=Count("usage")).filter(used__lt=F("orders")).order_by("created_at", "id").first()
            )
            if pack:
                charged_to = OrderUsage.ChargedTo.PACK
        try:
            with transaction.atomic():
                row = OrderUsage.objects.create(
                    restaurant_id=order.restaurant_id, subscription=sub, billing_period=period, order=order,
                    event_type=OrderUsage.Event.ORDER_COMPLETED, charged_to=charged_to, order_pack=pack,
                )
        except IntegrityError:
            return OrderUsage.objects.get(order=order, event_type=OrderUsage.Event.ORDER_COMPLETED), False
        return row, True


def expire_packs(now=None):
    """Mark packs whose period has ended as EXPIRED. Purely bookkeeping: capacity() already ignores them after the period ends."""
    now = now or timezone.now()
    return OrderPack.objects.filter(status=OrderPack.Status.ACTIVE, billing_period__ends_at__lte=now).update(status=OrderPack.Status.EXPIRED)
