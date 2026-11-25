"""Order packs, upgrades, downgrades, payment verification and webhooks (spec items 9, 10, 11, 15, 19)."""
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.orders.models import ActorType, Order, OrderStatus
from apps.orders.workflow import change_status
from apps.platform_admin import billing, services, usage
from apps.platform_admin.models import (
    BillingPeriod, OrderPack, OrderUsage, PaymentDetails, PaymentWebhookEvent, Plan, PlanChange, Subscription,
    SubscriptionPayment,
)
from apps.restaurants.models import MembershipRole

pytestmark = pytest.mark.django_db

SECRET = "whsec_test_secret"


# ---------------------------------------------------------------- fixtures and helpers
@pytest.fixture(autouse=True)
def webhook_secret(settings):
    settings.PAYMENT_WEBHOOK_SECRET = SECRET


@pytest.fixture
def details():
    return PaymentDetails.objects.create(bank_name="Example Bank", account_name="ServeFlow Ltd", account_number="0123456789")


def make_plan(name, price, allowance, pack=(None, None), interval="MONTHLY"):
    return Plan.objects.create(
        name=name, interval=interval, price=Decimal(price), included_orders=allowance, included_requests=10000,
        rate_limit_per_minute=60, pack_orders=pack[0], pack_price=Decimal(pack[1]) if pack[1] else None,
    )


@pytest.fixture
def starter(details):
    return make_plan("Starter", "3000.00", 2, pack=(5, "500.00"))


@pytest.fixture
def growth(details):
    return make_plan("Growth", "9000.00", 10, pack=(20, "1500.00"))


@pytest.fixture
def basic(details):
    return make_plan("Basic", "1500.00", 1)


def active_sub(restaurant, plan):
    now = timezone.now()
    start, end = now - timedelta(days=1), now + timedelta(days=29)
    sub = Subscription.objects.create(
        restaurant=restaurant, plan=plan, status="ACTIVE", started_at=start, current_period_start=start,
        current_period_end=end, billing_anchor=start,
    )
    usage.open_period(sub, plan, start, end)
    return sub


@pytest.fixture
def owner(shop, staff_login):
    return staff_login(shop.restaurant, MembershipRole.OWNER)


@pytest.fixture
def make_order(shop, order_in):
    counter = iter(range(1, 1000))
    return lambda status="PENDING": order_in(status, phone=f"+44207946{next(counter):04d}")


def complete(order):
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.SERVING)
    return change_status(order=order, to_status=OrderStatus.COMPLETED, actor_type=ActorType.SYSTEM)


def billing_url(name, shop):
    return reverse(name, kwargs={"slug": shop.restaurant.slug})


def buy_pack(api_client, shop):
    response = api_client.post(billing_url("billing-order-packs", shop))
    assert response.status_code in (200, 201), response.content
    return SubscriptionPayment.objects.get(reference=response.json()["payment"]["reference"])


def sign(raw):
    return hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()


def webhook(client, payment=None, *, status="success", event_id=None, amount=None, currency=None, signature=None, reference=None, provider_reference="txn_1"):
    body = {
        "event_id": event_id or uuid.uuid4().hex, "reference": reference or payment.reference, "status": status,
        "amount": str(amount if amount is not None else payment.amount), "currency": currency or payment.currency,
        "provider_reference": provider_reference,
    }
    raw = json.dumps(body).encode()
    return client.post(
        reverse("billing-webhook", kwargs={"provider": "generic"}), data=raw, content_type="application/json",
        HTTP_X_SIGNATURE=signature if signature is not None else sign(raw),
    )


def capacity(sub):
    return usage.capacity(usage.current_period(sub))


# ---------------------------------------------------------------- buying an order pack (spec 9, 10)
def test_starting_a_pack_purchase_adds_no_capacity_until_it_is_paid(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    pack = payment.order_pack
    assert (payment.kind, payment.status, payment.amount) == ("ORDER_PACK", "AWAITING_CONFIRMATION", Decimal("500.00"))
    assert (pack.status, pack.orders, pack.reference) == ("PENDING", 5, payment.reference)
    assert pack.billing_period == usage.current_period(sub)
    assert capacity(sub)["capacity"] == 2  # nothing added yet
    again = api_client.post(billing_url("billing-order-packs", shop))
    assert again.status_code == 200 and again.json()["payment"]["reference"] == payment.reference  # one open purchase at a time


def test_a_confirmed_pack_payment_adds_capacity(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    services.confirm_payment(payment.pk, None)
    payment.refresh_from_db()
    pack = payment.order_pack
    pack.refresh_from_db()
    assert payment.status == "CONFIRMED" and pack.status == "ACTIVE" and pack.activated_at is not None
    assert capacity(sub)["capacity"] == 7 and capacity(sub)["remaining"] == 7
    with pytest.raises(Exception):  # paid once, activated once
        services.confirm_payment(payment.pk, None)


def test_the_billing_overview_lists_packs_the_offer_and_payment_kinds(api_client, shop, starter, owner):
    active_sub(shop.restaurant, starter)
    body = api_client.get(billing_url("billing-overview", shop)).json()
    assert body["pack_offer"]["orders"] == 5 and body["pack_offer"]["price"] == "500.00"
    payment = buy_pack(api_client, shop)
    services.confirm_payment(payment.pk, None)
    body = api_client.get(billing_url("billing-overview", shop)).json()
    assert body["order_packs"][0]["status"] == "ACTIVE" and body["order_packs"][0]["remaining"] == 5
    assert [p["kind"] for p in body["payments"]] == ["ORDER_PACK"]
    assert body["open_payment"] is None  # a pack payment is never mistaken for the subscription payment


def test_packs_are_refused_without_an_offer_a_running_subscription_or_the_owner_role(api_client, shop, basic, staff_login, make_restaurant):
    other = make_restaurant()
    plain = active_sub(shop.restaurant, basic)  # a plan with no pack offer
    staff_login(shop.restaurant, MembershipRole.OWNER)
    refused = api_client.post(billing_url("billing-order-packs", shop))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "order_packs_unavailable"
    Subscription.objects.filter(pk=plain.pk).update(status="PAST_DUE")
    assert api_client.post(billing_url("billing-order-packs", shop)).status_code == 409
    staff_login(shop.restaurant, MembershipRole.MANAGER)
    assert api_client.post(billing_url("billing-order-packs", shop)).status_code == 403
    assert api_client.post(reverse("billing-order-packs", kwargs={"slug": other.slug})).status_code == 403  # not their restaurant


def test_a_pack_paid_after_its_period_ended_adds_nothing(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    past = timezone.now() - timedelta(hours=1)
    BillingPeriod.objects.filter(subscription=sub).update(starts_at=past - timedelta(days=30), ends_at=past)
    services.confirm_payment(payment.pk, None)
    pack = OrderPack.objects.get()
    assert pack.status == "EXPIRED" and pack.activated_at is None


def test_an_active_pack_expires_at_the_period_boundary(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    services.confirm_payment(buy_pack(api_client, shop).pk, None)
    period = usage.current_period(sub)
    assert usage.capacity(period)["capacity"] == 7
    after = period.ends_at + timedelta(seconds=1)
    assert usage.capacity(period, now=after)["capacity"] == 2
    usage.expire_packs(after)
    assert OrderPack.objects.get().status == "EXPIRED"


def test_an_owner_can_mark_a_payment_failed_and_the_pack_is_cancelled(api_client, shop, starter, owner, make_user):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    platform = make_user(is_staff=True, is_superuser=True)
    api_client.force_login(platform)
    url = reverse("platform-payment-fail", kwargs={"pk": payment.pk})
    assert api_client.post(url, {}, format="json").status_code == 409  # a reason is required
    assert api_client.post(url, {"reason": "Transfer never arrived"}, format="json").status_code == 204
    payment.refresh_from_db()
    assert (payment.status, payment.failure_reason) == ("FAILED", "Transfer never arrived")
    assert OrderPack.objects.get().status == "FAILED" and capacity(sub)["capacity"] == 2
    assert api_client.post(reverse("platform-payment-confirm", kwargs={"pk": payment.pk})).status_code == 409  # can't confirm afterwards


def test_ordinary_users_cannot_fail_or_confirm_platform_payments(api_client, shop, starter, owner):
    active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)  # signed in as the restaurant owner
    assert api_client.post(reverse("platform-payment-fail", kwargs={"pk": payment.pk}), {"reason": "x"}, format="json").status_code == 403
    assert api_client.post(reverse("platform-payment-confirm", kwargs={"pk": payment.pk})).status_code == 403


# ---------------------------------------------------------------- webhooks (spec 9, 10, 19)
def test_a_signed_success_webhook_activates_the_pack(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    response = webhook(api_client, payment)
    assert response.status_code == 200 and response.json() == {"status": "processed", "outcome": "confirmed"}
    payment.refresh_from_db()
    assert (payment.status, payment.provider, payment.provider_reference) == ("CONFIRMED", "GATEWAY", "txn_1")
    assert OrderPack.objects.get().status == "ACTIVE" and capacity(sub)["capacity"] == 7
    event = PaymentWebhookEvent.objects.get()
    assert (event.outcome, event.payment_id, len(event.payload_sha256)) == ("confirmed", payment.pk, 64)


def test_a_webhook_with_a_bad_or_missing_signature_changes_nothing(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    for signature in ("", "deadbeef", sign(b"another body")):
        response = webhook(api_client, payment, signature=signature)
        assert response.status_code == 401 and response.json()["error"]["code"] == "invalid_signature"
    payment.refresh_from_db()
    assert payment.status == "AWAITING_CONFIRMATION" and capacity(sub)["capacity"] == 2
    assert PaymentWebhookEvent.objects.count() == 0


def test_webhooks_are_off_until_a_secret_is_configured(api_client, settings, shop, starter, owner):
    active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    settings.PAYMENT_WEBHOOK_SECRET = ""
    response = webhook(api_client, payment, signature=sign(b"x"))
    assert response.status_code == 503 and response.json()["error"]["code"] == "webhooks_disabled"
    payment.refresh_from_db()
    assert payment.status == "AWAITING_CONFIRMATION"


def test_a_failed_webhook_marks_the_payment_failed_and_adds_no_capacity(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    assert webhook(api_client, payment, status="failed").json()["outcome"] == "payment_failed"
    payment.refresh_from_db()
    assert payment.status == "FAILED" and OrderPack.objects.get().status == "FAILED"
    assert capacity(sub)["capacity"] == 2


@pytest.mark.parametrize("amount, currency", [("499.00", None), ("5000.00", None), ("500.00", "USD")])
def test_a_webhook_for_the_wrong_amount_or_currency_does_not_activate_anything(api_client, shop, starter, owner, amount, currency):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    response = webhook(api_client, payment, amount=amount, currency=currency)
    assert response.status_code == 200 and response.json()["outcome"] == "amount_mismatch"
    payment.refresh_from_db()
    assert payment.status == "AWAITING_CONFIRMATION" and OrderPack.objects.get().status == "PENDING"
    assert capacity(sub)["capacity"] == 2


def test_the_same_webhook_twice_is_processed_once(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    first = webhook(api_client, payment, event_id="evt_1")
    retry = webhook(api_client, payment, event_id="evt_1")
    assert first.json()["status"] == "processed" and retry.status_code == 200 and retry.json() == {"status": "duplicate", "outcome": "duplicate"}
    assert PaymentWebhookEvent.objects.count() == 1 and capacity(sub)["capacity"] == 7  # not 12


def test_a_different_event_for_an_already_confirmed_payment_changes_nothing(api_client, shop, starter, owner):
    sub = active_sub(shop.restaurant, starter)
    payment = buy_pack(api_client, shop)
    webhook(api_client, payment, event_id="evt_a")
    again = webhook(api_client, payment, event_id="evt_b", provider_reference="txn_2")
    assert again.json()["outcome"] == "already_confirmed"
    assert capacity(sub)["capacity"] == 7 and SubscriptionPayment.objects.get().provider_reference == "txn_1"


def test_an_unknown_reference_and_a_malformed_body_are_handled_safely(api_client):
    unknown = webhook(api_client, reference="SF-NOPE", amount="1.00", currency="NGN")
    assert unknown.status_code == 200 and unknown.json()["outcome"] == "unknown_reference"
    raw = b'{"event_id": "x"}'
    bad = api_client.post(reverse("billing-webhook", kwargs={"provider": "generic"}), data=raw, content_type="application/json", HTTP_X_SIGNATURE=sign(raw))
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_event"
    raw = b"{}"
    assert api_client.post(reverse("billing-webhook", kwargs={"provider": "other"}), data=raw, content_type="application/json", HTTP_X_SIGNATURE=sign(raw)).status_code == 404


def test_a_webhook_can_confirm_a_subscription_payment_too(api_client, shop, starter, owner):
    sub = services.start_trial(shop.restaurant, starter)
    api_client.post(billing_url("billing-subscribe", shop), {"plan_id": starter.pk}, format="json")
    payment, _ = billing.open_payment(shop.restaurant, owner)
    assert webhook(api_client, payment).json()["outcome"] == "confirmed"
    sub.refresh_from_db()
    assert sub.status == "ACTIVE" and sub.plan == starter and payment.kind == "SUBSCRIPTION"


# ---------------------------------------------------------------- upgrades (immediate, explicit)
def test_an_upgrade_applies_after_the_difference_is_paid_and_keeps_recorded_usage(api_client, shop, starter, growth, owner, make_order):
    sub = active_sub(shop.restaurant, starter)
    for _ in range(2):
        complete(make_order())
    period = usage.current_period(sub)
    assert usage.capacity(period)["remaining"] == 0

    response = api_client.post(billing_url("billing-subscribe", shop), {"plan_id": growth.pk}, format="json")
    assert response.status_code == 201
    change, payment = PlanChange.objects.get(), SubscriptionPayment.objects.get()
    assert (change.kind, change.status, change.amount_due) == ("UPGRADE", "PENDING", Decimal("6000.00"))  # 9000 - 3000, no proration
    assert (payment.kind, payment.amount, payment.plan_change_id) == ("UPGRADE", Decimal("6000.00"), change.pk)
    period.refresh_from_db()
    assert period.included_orders == 2  # nothing changes before payment

    services.confirm_payment(payment.pk, None)
    period.refresh_from_db(), change.refresh_from_db(), sub.refresh_from_db()
    assert sub.plan == growth and period.plan == growth and period.plan_name == "Growth" and period.included_orders == 10
    assert (change.status, change.allowance_before, change.allowance_after, change.billing_period_id) == ("APPLIED", 2, 10, period.pk)
    cap = usage.capacity(period)
    assert (cap["used"], cap["remaining"]) == (2, 8)  # recorded usage stays; the new allowance covers the rest
    assert OrderUsage.objects.filter(billing_period=period).count() == 2
    assert (period.starts_at, BillingPeriod.objects.count()) == (usage.current_period(sub).starts_at, 1)  # same period, not a new one


def test_an_upgrade_cannot_be_applied_by_the_wrong_amount(shop, starter, growth, owner):
    active_sub(shop.restaurant, starter)
    billing.choose_plan(shop.restaurant, growth, owner)
    payment = SubscriptionPayment.objects.get()
    SubscriptionPayment.objects.filter(pk=payment.pk).update(amount=Decimal("100.00"))
    with pytest.raises(Exception) as raised:
        services.confirm_payment(payment.pk, None)
    assert raised.value.get_codes() == "amount_mismatch"
    assert PlanChange.objects.get().status == "PENDING"


# ---------------------------------------------------------------- downgrades (next anniversary) (spec 15)
def test_a_downgrade_waits_for_the_next_anniversary(api_client, shop, starter, growth, basic, owner):
    sub = active_sub(shop.restaurant, growth)
    period = usage.current_period(sub)
    response = api_client.post(billing_url("billing-subscribe", shop), {"plan_id": basic.pk}, format="json")
    assert response.status_code == 201 and response.json()["pending_plan_change"]["kind"] == "DOWNGRADE"
    sub.refresh_from_db()
    change = PlanChange.objects.get()
    assert (change.kind, change.status, change.effective_at) == ("DOWNGRADE", "PENDING", sub.current_period_end)
    assert sub.plan == growth and sub.pending_plan == basic
    period.refresh_from_db()
    assert period.included_orders == 10 and period.plan == growth  # the running period is untouched

    payment, _ = billing.open_payment(shop.restaurant, owner)  # the renewal is priced at the NEW plan
    assert payment.amount == Decimal("1500.00")
    services.confirm_payment(payment.pk, None)
    sub.refresh_from_db()
    next_period = BillingPeriod.objects.get(subscription=sub, plan=basic)
    assert next_period.starts_at == period.ends_at and next_period.included_orders == 1
    assert sub.plan == growth and sub.pending_plan == basic  # still on the old plan until the anniversary
    assert usage.current_period(sub).pk == period.pk and usage.current_period(sub).included_orders == 10

    assert services.apply_due_plan_changes(now=period.ends_at - timedelta(minutes=1)) == 0
    assert services.apply_due_plan_changes(now=period.ends_at + timedelta(minutes=1)) == 1
    sub.refresh_from_db(), change.refresh_from_db()
    assert sub.plan == basic and sub.pending_plan is None and change.status == "APPLIED"


def test_paying_late_applies_a_waiting_downgrade_at_once(api_client, shop, growth, basic, owner):
    sub = active_sub(shop.restaurant, growth)
    api_client.post(billing_url("billing-subscribe", shop), {"plan_id": basic.pk}, format="json")
    ended = timezone.now() - timedelta(hours=2)
    BillingPeriod.objects.filter(subscription=sub).update(starts_at=ended - timedelta(days=30), ends_at=ended)
    Subscription.objects.filter(pk=sub.pk).update(status="PAST_DUE", current_period_end=ended)
    payment, _ = billing.open_payment(shop.restaurant, owner)
    services.confirm_payment(payment.pk, None)
    sub.refresh_from_db()
    assert sub.plan == basic and sub.pending_plan is None and sub.status == "ACTIVE"
    assert PlanChange.objects.get().status == "APPLIED"


def test_a_waiting_plan_change_can_be_cancelled(api_client, shop, growth, basic, owner):
    sub = active_sub(shop.restaurant, growth)
    api_client.post(billing_url("billing-subscribe", shop), {"plan_id": basic.pk}, format="json")
    assert api_client.post(billing_url("billing-plan-change-cancel", shop)).status_code == 200
    sub.refresh_from_db()
    assert sub.pending_plan is None and PlanChange.objects.get().status == "CANCELLED"
    assert api_client.post(billing_url("billing-plan-change-cancel", shop)).status_code == 409


def test_cancelling_a_waiting_upgrade_fails_its_payment(api_client, shop, starter, growth, owner):
    active_sub(shop.restaurant, starter)
    api_client.post(billing_url("billing-subscribe", shop), {"plan_id": growth.pk}, format="json")
    api_client.post(billing_url("billing-plan-change-cancel", shop))
    payment = SubscriptionPayment.objects.get()
    assert payment.status == "FAILED" and PlanChange.objects.get().status == "CANCELLED"


def test_a_restaurant_can_switch_plan_at_any_time(api_client, shop, starter, growth, basic, owner):
    sub = active_sub(shop.restaurant, starter)
    url = billing_url("billing-subscribe", shop)

    same = api_client.post(url, {"plan_id": starter.pk}, format="json")
    assert same.status_code == 409 and same.json()["error"]["code"] == "same_plan"  # nothing to do, nothing waiting

    yearly = make_plan("Yearly", "30000.00", 50, interval="YEARLY")
    assert api_client.post(url, {"plan_id": yearly.pk}, format="json").status_code == 201  # monthly to yearly: at the next renewal
    change = PlanChange.objects.get()
    assert (change.kind, change.status, change.to_plan) == ("DOWNGRADE", "PENDING", yearly) and not SubscriptionPayment.objects.exists()

    assert api_client.post(url, {"plan_id": growth.pk}, format="json").status_code == 201  # changing your mind replaces it
    change.refresh_from_db()
    assert change.status == "CANCELLED"
    upgrade = PlanChange.objects.get(status="PENDING")
    assert (upgrade.kind, upgrade.to_plan) == ("UPGRADE", growth)

    assert api_client.post(url, {"plan_id": starter.pk}, format="json").status_code == 201  # choosing the current plan drops the change
    upgrade.refresh_from_db()
    sub.refresh_from_db()
    assert upgrade.status == "CANCELLED" and sub.pending_plan is None and not PlanChange.objects.filter(status="PENDING").exists()
    assert SubscriptionPayment.objects.get().status == "FAILED"  # its waiting upgrade payment was closed


def test_an_overdue_restaurant_can_switch_and_its_next_payment_follows(api_client, shop, starter, growth, owner):
    sub = active_sub(shop.restaurant, starter)
    Subscription.objects.filter(pk=sub.pk).update(status="PAST_DUE")
    assert api_client.post(billing_url("billing-subscribe", shop), {"plan_id": growth.pk}, format="json").status_code == 201
    sub.refresh_from_db()
    assert sub.next_plan == growth and not PlanChange.objects.exists()
    payment, _ = billing.open_payment(shop.restaurant, owner)
    assert payment.amount == Decimal("9000.00")  # priced at the plan they picked


def test_a_plans_pack_offer_needs_both_size_and_price():
    from apps.platform_admin.serializers import PlanSerializer

    plan = make_plan("Edit", "1000.00", 5)
    only_size = PlanSerializer(plan, data={"pack_orders": 10}, partial=True)
    assert not only_size.is_valid() and "pack_orders" in only_size.errors
    both = PlanSerializer(plan, data={"pack_orders": 10, "pack_price": "800.00"}, partial=True)
    assert both.is_valid(), both.errors
    zero = PlanSerializer(plan, data={"pack_orders": 0, "pack_price": "800.00"}, partial=True)
    assert not zero.is_valid()
