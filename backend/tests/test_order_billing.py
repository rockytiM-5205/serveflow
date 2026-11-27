"""Completed-order billing: the usage ledger, allowance and order packs, anniversary periods, and the order lifecycle.

Covers spec items 1-8, 11-14, 16, 18 and 20 (payment-webhook and downgrade items arrive with Phase 3).
"""
import re
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common.exceptions import Conflict
from apps.orders.models import ActorType, Order, OrderStatus, Payment
from apps.orders.workflow import change_status
from apps.platform_admin import locks, services, usage
from apps.platform_admin.models import (
    BillingPeriod, OrderPack, OrderUsage, Plan, Subscription, SubscriptionPayment,
)
from apps.restaurants.models import MembershipRole

pytestmark = pytest.mark.django_db

def _later():
    """A pickup time that is allowed: two hours from now."""
    from datetime import timedelta

    from django.utils import timezone

    return (timezone.now() + timedelta(hours=2)).isoformat()



# ---------------------------------------------------------------- fixtures and helpers
@pytest.fixture
def plan():
    return Plan.objects.create(
        name="Starter", interval="MONTHLY", price=Decimal("3000.00"), included_orders=2, included_requests=10000,
        rate_limit_per_minute=60,
    )


@pytest.fixture
def subscribe(plan):
    """Give a restaurant an ACTIVE subscription with one billing period around now."""

    def _subscribe(restaurant, the_plan=None, allowance=None):
        the_plan = the_plan or plan
        if allowance is not None:
            the_plan = Plan.objects.create(
                name=f"Plan {allowance}", interval="MONTHLY", price=Decimal("1.00"), included_orders=allowance,
                included_requests=1000, rate_limit_per_minute=60,
            )
        now = timezone.now()
        start, end = now - timedelta(days=1), now + timedelta(days=29)
        sub = Subscription.objects.create(
            restaurant=restaurant, plan=the_plan, status="ACTIVE", started_at=start, current_period_start=start,
            current_period_end=end, billing_anchor=start,
        )
        usage.open_period(sub, the_plan, start, end)
        return sub

    return _subscribe


@pytest.fixture
def make_order(shop, order_in):
    counter = iter(range(1, 1000))

    def _make(status="PENDING"):
        return order_in(status, phone=f"+44207946{next(counter):04d}")

    return _make


def complete(order):
    """Complete an order through the real state machine (the only place usage is recorded)."""
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.SERVING)
    return change_status(order=order, to_status=OrderStatus.COMPLETED, actor_type=ActorType.SYSTEM)


def usage_count(restaurant):
    return OrderUsage.objects.filter(restaurant=restaurant).count()


def code(response):
    return response.json()["error"]["code"]


# ---------------------------------------------------------------- usage is counted exactly once (spec 1-4)
def test_a_completed_order_is_counted_exactly_once(shop, subscribe, make_order):
    sub = subscribe(shop.restaurant)
    order = make_order()
    complete(order)
    rows = OrderUsage.objects.filter(order=order)
    assert rows.count() == 1
    row = rows.get()
    assert (row.event_type, row.charged_to, row.subscription_id) == ("ORDER_COMPLETED", "PLAN", sub.pk)
    assert row.billing_period.included_orders == 2


def test_submitted_confirmed_and_preparing_orders_are_not_counted(api_client, shop, subscribe, make_order, staff_login):
    subscribe(shop.restaurant)
    order = make_order()
    staff_login(shop.restaurant, MembershipRole.STAFF)
    for step in ("CONFIRMED", "SERVING", "READY_FOR_PICKUP"):
        Order.objects.filter(pk=order.pk).update(payment_status="PAID")  # preparing needs a confirmed payment
        response = api_client.post(
            reverse("staff-order-transition", kwargs={"slug": shop.restaurant.slug, "public_id": order.public_id}),
            {"to_status": step}, format="json",
        )
        assert response.status_code == 200, response.content
        assert usage_count(shop.restaurant) == 0
    order.refresh_from_db()
    assert order.ready_at is not None and order.completed_at is None


def test_cancelled_and_rejected_orders_are_never_counted(shop, subscribe, make_order):
    subscribe(shop.restaurant)
    cancelled, rejected = make_order(), make_order()
    change_status(order=cancelled, to_status=OrderStatus.CANCELLED, actor_type=ActorType.CUSTOMER)
    change_status(order=rejected, to_status=OrderStatus.REJECTED, actor_type=ActorType.STAFF, reason="Out of rice")
    assert usage_count(shop.restaurant) == 0


def test_a_duplicate_completion_does_not_count_twice(shop, subscribe, make_order):
    subscribe(shop.restaurant)
    order = make_order()
    complete(order)
    with pytest.raises(Conflict):  # the state machine refuses COMPLETED -> COMPLETED
        change_status(order=order, to_status=OrderStatus.COMPLETED, actor_type=ActorType.SYSTEM)
    row, created = usage.record_completion(Order.objects.get(pk=order.pk))  # and the ledger itself is idempotent
    assert created is False and row is not None
    assert usage_count(shop.restaurant) == 1


def test_the_database_allows_one_usage_row_per_order_event(shop, subscribe, make_order):
    from django.db import IntegrityError, transaction

    sub = subscribe(shop.restaurant)
    order = make_order()
    complete(order)
    period = BillingPeriod.objects.get(subscription=sub)
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderUsage.objects.create(
            restaurant=shop.restaurant, subscription=sub, billing_period=period, order=order, charged_to="PLAN",
        )


def test_a_restaurant_without_a_subscription_is_not_metered(shop, make_order):
    complete(make_order())
    assert usage_count(shop.restaurant) == 0


# ---------------------------------------------------------------- one allowance for every channel (spec 6)
def test_marketplace_and_api_orders_share_one_allowance(settings, shop, subscribe, place):
    settings.PLATFORM_ENFORCE_API_KEYS = True
    sub = subscribe(shop.restaurant)  # allowance 2
    _, secret = services.create_credential(actor=None, customer=shop.restaurant, name="Site", environment="live")

    marketplace = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460001")
    via_api = APIClient().post(
        reverse("public-order-create", kwargs={"slug": shop.restaurant.slug}),
        {"customer_name": "Bola", "customer_phone": "+442079460002", "fulfilment_type": "PICKUP", "pickup_at": _later(),
         "items": [{"menu_item_id": shop.rice.pk, "quantity": 1}]},
        format="json", HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex, HTTP_AUTHORIZATION=f"Bearer {secret}",
    )
    assert marketplace.status_code == 201 and via_api.status_code == 201, via_api.content
    assert sorted(Order.objects.values_list("source", flat=True)) == ["API", "MARKETPLACE"]
    for order in Order.objects.all():
        complete(order)
    assert usage.summary(sub)["completed_orders"] == 2 and usage.summary(sub)["remaining"] == 0
    blocked = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460003")
    assert blocked.status_code == 402 and code(blocked) == "ORDER_LIMIT_REACHED"


# ---------------------------------------------------------------- quota exhaustion (spec 7, 8)
def test_reaching_the_allowance_blocks_new_orders_with_a_structured_error(shop, subscribe, make_order, place):
    subscribe(shop.restaurant, allowance=1)
    complete(make_order())
    response = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079469999")
    assert response.status_code == 402
    error = response.json()["error"]
    assert error["code"] == "ORDER_LIMIT_REACHED"
    assert "upgrade" in error["message"] and error["details"]["action"] == "upgrade_or_purchase_order_pack"
    assert error["details"]["allowance"] == 1 and error["details"]["completed_orders"] == 1
    assert Order.objects.count() == 1  # nothing was created


def test_orders_accepted_before_the_limit_can_still_be_completed(shop, subscribe, make_order):
    sub = subscribe(shop.restaurant, allowance=1)
    first, second = make_order(), make_order()  # both accepted while there was room
    complete(first)
    complete(second)  # staff are never stuck mid-service
    charges = list(OrderUsage.objects.order_by("id").values_list("charged_to", flat=True))
    assert charges == ["PLAN", "OVERAGE"]
    summary = usage.summary(sub)
    assert summary["completed_orders"] == 2 and summary["remaining"] == 0 and summary["limit_reached"] is True


def test_the_billing_dashboard_stays_reachable_when_the_allowance_is_used_up(api_client, shop, subscribe, make_order, staff_login):
    subscribe(shop.restaurant, allowance=1)
    complete(make_order())
    staff_login(shop.restaurant, MembershipRole.OWNER)
    response = api_client.get(reverse("billing-overview", kwargs={"slug": shop.restaurant.slug}))
    assert response.status_code == 200
    body = response.json()["usage"]
    assert (body["included_orders"], body["completed_orders"], body["remaining"], body["percent_used"]) == (1, 1, 0, 100)
    assert body["warning_level"] == 100 and body["limit_reached"] is True
    orders = api_client.get(reverse("staff-orders", kwargs={"slug": shop.restaurant.slug}))
    assert orders.status_code == 200  # history stays available


def test_capacity_reports_the_warning_level_as_usage_grows(shop, subscribe, make_order):
    sub = subscribe(shop.restaurant, allowance=10)
    period = usage.current_period(sub)
    seen = []
    for _ in range(10):
        complete(make_order())
        seen.append(usage.capacity(period)["warning"])
    # 10%, 20% ... 70% show nothing; 80% is the 75 warning; 90% the 90 warning; 100% the limit
    assert seen == [None] * 7 + [75, 90, 100]


def test_percentages_map_to_warning_levels():
    for percent, level in [(0, None), (74, None), (75, 75), (89, 75), (90, 90), (99, 90), (100, 100)]:
        assert next((lv for lv in usage.WARNING_LEVELS if percent >= lv), None) == level


def test_a_stale_cache_cannot_let_an_expired_subscription_take_orders(settings, shop, subscribe):
    settings.PLATFORM_ENFORCE_SUBSCRIPTIONS = True
    sub = subscribe(shop.restaurant)
    locks.get_state(shop.restaurant.slug)  # primes the cache as "not locked"
    Subscription.objects.filter(pk=sub.pk).update(status="EXPIRED", current_period_end=timezone.now() - timedelta(days=10))
    with pytest.raises(Conflict) as raised:
        usage.assert_can_accept_orders(shop.restaurant)
    assert raised.value.get_codes() == "subscription_inactive"


# ---------------------------------------------------------------- order packs (spec 9-11, ledger side)
def test_an_active_pack_adds_capacity_and_is_used_after_the_plan_allowance(shop, subscribe, make_order, place):
    sub = subscribe(shop.restaurant, allowance=1)
    period = usage.current_period(sub)
    pack = OrderPack.objects.create(
        restaurant=shop.restaurant, billing_period=period, orders=2, price=Decimal("500.00"), currency="NGN",
        reference="PACK-1", status="ACTIVE", activated_at=timezone.now(),
    )
    orders = [make_order() for _ in range(3)]
    for order in orders:
        complete(order)
    assert list(OrderUsage.objects.order_by("id").values_list("charged_to", flat=True)) == ["PLAN", "PACK", "PACK"]
    assert OrderUsage.objects.filter(order_pack=pack).count() == 2
    cap = usage.capacity(period)
    assert (cap["capacity"], cap["used"], cap["remaining"]) == (3, 3, 0)
    assert place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460777").status_code == 402


@pytest.mark.parametrize("status", ["PENDING", "FAILED", "EXPIRED"])
def test_a_pack_that_is_not_active_adds_no_capacity(shop, subscribe, status):
    sub = subscribe(shop.restaurant, allowance=1)
    period = usage.current_period(sub)
    OrderPack.objects.create(
        restaurant=shop.restaurant, billing_period=period, orders=50, price=Decimal("1.00"), currency="NGN",
        reference=f"PACK-{status}", status=status,
    )
    cap = usage.capacity(period)
    assert (cap["capacity"], cap["remaining"]) == (1, 1)


def test_a_pack_expires_with_its_billing_period(shop, subscribe):
    sub = subscribe(shop.restaurant, allowance=1)
    period = usage.current_period(sub)
    pack = OrderPack.objects.create(
        restaurant=shop.restaurant, billing_period=period, orders=5, price=Decimal("1.00"), currency="NGN",
        reference="PACK-E", status="ACTIVE", activated_at=timezone.now(),
    )
    assert usage.capacity(period)["capacity"] == 6
    after = period.ends_at + timedelta(seconds=1)
    assert usage.capacity(period, now=after)["capacity"] == 1  # nothing rolls over, even before the bookkeeping job runs
    usage.expire_packs(after)
    pack.refresh_from_db()
    assert pack.status == "EXPIRED"


# ---------------------------------------------------------------- anniversary periods (spec 12-14)
@pytest.mark.parametrize(
    "anchor, start, interval, expected_end",
    [
        (datetime(2027, 1, 31, 9, tzinfo=dt_timezone.utc), datetime(2027, 1, 31, 9, tzinfo=dt_timezone.utc), "MONTHLY", datetime(2027, 2, 28, 9, tzinfo=dt_timezone.utc)),
        (datetime(2027, 1, 31, 9, tzinfo=dt_timezone.utc), datetime(2027, 2, 28, 9, tzinfo=dt_timezone.utc), "MONTHLY", datetime(2027, 3, 31, 9, tzinfo=dt_timezone.utc)),
        (datetime(2028, 1, 31, 9, tzinfo=dt_timezone.utc), datetime(2028, 1, 31, 9, tzinfo=dt_timezone.utc), "MONTHLY", datetime(2028, 2, 29, 9, tzinfo=dt_timezone.utc)),
        (datetime(2026, 11, 12, 9, tzinfo=dt_timezone.utc), datetime(2026, 11, 12, 9, tzinfo=dt_timezone.utc), "MONTHLY", datetime(2026, 12, 12, 9, tzinfo=dt_timezone.utc)),
        (datetime(2028, 2, 29, 9, tzinfo=dt_timezone.utc), datetime(2028, 2, 29, 9, tzinfo=dt_timezone.utc), "YEARLY", datetime(2029, 2, 28, 9, tzinfo=dt_timezone.utc)),
    ],
)
def test_period_ends_follow_the_anchor_day_even_across_short_months(anchor, start, interval, expected_end):
    assert usage.period_end(anchor, start, interval) == expected_end


def _pay(sub, plan):
    payment = SubscriptionPayment.objects.create(
        subscription=sub, reference=f"SF-{uuid.uuid4().hex[:8].upper()}", amount=plan.price, currency=plan.currency,
        transacted_at=timezone.now(),
    )
    return services.confirm_payment(payment.pk, None)


def test_paying_after_the_trial_opens_a_period_and_paying_early_opens_the_next_one(shop, plan):
    sub = services.start_trial(shop.restaurant, plan)
    assert BillingPeriod.objects.filter(subscription=sub).count() == 1  # the trial's own period
    trial_period = BillingPeriod.objects.get(subscription=sub)
    assert trial_period.included_orders == services.trial_plan().included_orders

    _pay(sub, plan)
    sub.refresh_from_db()
    first = BillingPeriod.objects.filter(subscription=sub, plan=plan).get()
    assert sub.billing_anchor == first.starts_at and (sub.current_period_start, sub.current_period_end) == (first.starts_at, first.ends_at)
    assert first.ends_at == usage.add_months(first.starts_at, 1)
    trial_period.refresh_from_db()
    assert trial_period.ends_at <= first.starts_at  # periods never overlap

    sub.next_plan = plan
    sub.save(update_fields=["next_plan"])
    _pay(sub, plan)  # renewing while still paid up
    second = BillingPeriod.objects.filter(subscription=sub, plan=plan).order_by("starts_at").last()
    assert second.pk != first.pk and second.starts_at == first.ends_at
    assert second.ends_at == usage.add_months(first.starts_at, 2)  # measured from the anchor, not from the previous end


def test_usage_history_survives_renewal_and_the_new_period_starts_empty(shop, plan, make_order):
    sub = services.start_trial(shop.restaurant, plan)
    _pay(sub, plan)
    sub.refresh_from_db()
    for _ in range(2):
        complete(make_order())
    first = BillingPeriod.objects.filter(subscription=sub, plan=plan).get()
    assert usage.capacity(first)["used"] == 2

    sub.next_plan = plan
    sub.save(update_fields=["next_plan"])
    _pay(sub, plan)
    second = BillingPeriod.objects.filter(subscription=sub, plan=plan).order_by("starts_at").last()
    assert usage.capacity(first)["used"] == 2  # history untouched
    assert usage.capacity(second, now=second.starts_at + timedelta(minutes=1))["used"] == 0  # reset on the anniversary
    assert OrderUsage.objects.filter(billing_period=first).count() == 2


def test_orders_count_in_the_period_in_which_they_complete(shop, plan, make_order):
    sub = services.start_trial(shop.restaurant, plan)
    _pay(sub, plan)
    order = make_order()
    complete(order)
    assert OrderUsage.objects.get(order=order).billing_period.starts_at <= timezone.now()


def test_editing_a_plan_never_rewrites_an_existing_period(shop, subscribe):
    sub = subscribe(shop.restaurant, allowance=5)
    Plan.objects.filter(pk=sub.plan_id).update(included_orders=500)
    assert usage.current_period(sub).included_orders == 5


def test_a_lapsed_subscription_in_its_grace_window_uses_its_last_period(settings, shop, subscribe):
    settings.BILLING_GRACE_DAYS = 3
    sub = subscribe(shop.restaurant, allowance=5)
    end = timezone.now() - timedelta(days=1)
    BillingPeriod.objects.filter(subscription=sub).update(starts_at=end - timedelta(days=30), ends_at=end)
    Subscription.objects.filter(pk=sub.pk).update(status="PAST_DUE", current_period_end=end)
    sub.refresh_from_db()
    assert usage.current_period(sub) is not None  # grace: no free reset
    assert usage.current_period(sub, now=end + timedelta(days=4)) is None


# ---------------------------------------------------------------- isolation and idempotency (spec 16, 18)
def test_restaurant_a_cannot_read_restaurant_bs_billing(api_client, shop, subscribe, make_restaurant, staff_login):
    other = make_restaurant()
    subscribe(other)
    staff_login(shop.restaurant, MembershipRole.OWNER)
    assert api_client.get(reverse("billing-overview", kwargs={"slug": other.slug})).status_code == 403
    assert api_client.get(reverse("billing-overview", kwargs={"slug": shop.restaurant.slug})).status_code == 200


def test_usage_rows_are_only_those_of_the_restaurant_that_completed_the_order(shop, subscribe, make_restaurant, make_order):
    other = make_restaurant()
    subscribe(other)
    subscribe(shop.restaurant)
    complete(make_order())
    assert usage_count(shop.restaurant) == 1 and usage_count(other) == 0


def test_a_retried_request_creates_no_second_order_and_is_not_blocked_by_the_limit(shop, subscribe, place, make_order):
    subscribe(shop.restaurant, allowance=1)
    key = uuid.uuid4().hex
    first = place(shop.restaurant, [(shop.rice.pk, 1)], key=key, phone="+442079460010")
    assert first.status_code == 201
    complete(Order.objects.get())  # the allowance is now used up
    retry = place(shop.restaurant, [(shop.rice.pk, 1)], key=key, phone="+442079460010")
    assert retry.status_code == 201 and retry.headers["Idempotent-Replay"] == "true"
    assert retry.json()["token"] == first.json()["token"]
    assert Order.objects.count() == 1
    fresh = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460011")
    assert fresh.status_code == 402 and code(fresh) == "ORDER_LIMIT_REACHED"


# ---------------------------------------------------------------- history is permanent (spec 20)
def test_a_refunded_completed_order_keeps_its_usage_record(shop, subscribe, make_order, make_user):
    subscribe(shop.restaurant)
    order = make_order()
    complete(order)
    payment = Payment.objects.create(
        order=order, restaurant=shop.restaurant, amount="5.00", currency="USD", method="CASH", recorded_by=make_user(),
    )
    Payment.objects.filter(pk=payment.pk).update(status="VOIDED")  # the payment is reversed; the order stays counted
    assert OrderUsage.objects.filter(order=order).count() == 1


def test_usage_records_cannot_be_edited_or_deleted(shop, subscribe, make_order):
    subscribe(shop.restaurant)
    complete(make_order())
    row = OrderUsage.objects.get()
    with pytest.raises(RuntimeError):
        row.delete()
    row.charged_to = "OVERAGE"
    with pytest.raises(RuntimeError):
        row.save()


# ---------------------------------------------------------------- lifecycle and references
def test_every_order_gets_a_readable_unique_reference_that_grants_no_access(api_client, shop, place):
    first = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460021").json()
    second = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460022").json()
    pattern = re.compile(rf"^{shop.restaurant.order_prefix}-[2-9A-HJKMNP-Z]{{5}}$")
    assert pattern.match(first["reference"]) and pattern.match(second["reference"])
    assert first["reference"] != second["reference"]
    lookup = api_client.get(reverse("public-order", kwargs={"token": first["reference"]}))
    assert lookup.status_code == 404  # only the signed link opens an order


def test_the_lifecycle_runs_through_ready_to_completed(shop, make_order):
    order = make_order()
    for step in ("CONFIRMED", "SERVING", "READY_FOR_PICKUP", "COMPLETED"):
        Order.objects.filter(pk=order.pk).update(payment_status="PAID")
        order = change_status(order=order, to_status=step, actor_type=ActorType.STAFF, actor_user=None)
    assert order.ready_at is not None and order.completed_at is not None and order.ready_at <= order.completed_at
    with pytest.raises(Conflict):
        change_status(order=order, to_status=OrderStatus.CANCELLED, actor_type=ActorType.MANAGER, reason="x")


def test_cancelling_a_ready_order_needs_a_manager_who_acknowledges_it(shop, make_order):
    from rest_framework.exceptions import PermissionDenied, ValidationError

    order = make_order()
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.READY_FOR_PICKUP)
    with pytest.raises(PermissionDenied):
        change_status(order=order, to_status=OrderStatus.CANCELLED, actor_type=ActorType.STAFF, reason="x")
    with pytest.raises(ValidationError):
        change_status(order=order, to_status=OrderStatus.CANCELLED, actor_type=ActorType.MANAGER, reason="x")
    change_status(order=order, to_status=OrderStatus.CANCELLED, actor_type=ActorType.MANAGER, reason="x", acknowledge_serving=True)
    assert usage_count(shop.restaurant) == 0


# ---------------------------------------------------------------- paid orders reserve capacity (no queue-then-complete bypass)
def test_paid_orders_reserve_capacity_so_queued_orders_cannot_all_finish_beyond_the_allowance(shop, subscribe, make_order, place, staff_login):
    from apps.orders.services import record_payment
    from apps.platform_admin.usage import OrderLimitReached

    subscribe(shop.restaurant, allowance=2)
    staff = staff_login(shop.restaurant)
    orders = [make_order() for _ in range(4)]  # unpaid orders reserve nothing, so all four can be queued
    for order in orders[:2]:
        record_payment(order=order, actor_user=staff, method="CASH", amount=order.total)
    with pytest.raises(OrderLimitReached):  # a third paid order would finish beyond the allowance
        record_payment(order=orders[2], actor_user=staff, method="CASH", amount=orders[2].total)
    orders[2].refresh_from_db()
    assert orders[2].payment_status != "PAID" and not Payment.objects.filter(order=orders[2]).exists()
    blocked = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079468888")  # and new orders are refused too
    assert blocked.status_code == 402 and code(blocked) == "ORDER_LIMIT_REACHED"
    complete(orders[0])
    complete(orders[1])
    assert usage.summary(Subscription.objects.get(restaurant=shop.restaurant))["completed_orders"] == 2
    assert OrderUsage.objects.filter(restaurant=shop.restaurant, charged_to="OVERAGE").count() == 0


def test_unpaid_orders_do_not_use_up_the_allowance(shop, subscribe, make_order, place):
    subscribe(shop.restaurant, allowance=2)
    for _ in range(5):
        make_order()  # five unpaid orders queued by anyone
    assert place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079467777").status_code == 201
