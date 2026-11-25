"""Owner API (docs/owner-api-contract.md). Needs PostgreSQL like the rest of the suite."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.platform_admin import services
from apps.platform_admin.models import (
    ApiCredential, ApiUsageDaily, Plan, PlatformAuditEvent, Subscription, SubscriptionPayment,
)
from apps.restaurants.models import MembershipRole

P = "/api/v1/platform"


@pytest.fixture
def owner(make_user):
    return make_user(is_staff=True, is_superuser=True)


@pytest.fixture
def owner_client(api_client, owner):
    api_client.force_login(owner)
    return api_client


@pytest.fixture
def plan(db):
    return Plan.objects.create(name="Starter", interval="MONTHLY", price=Decimal("3000.00"), included_requests=10000, rate_limit_per_minute=60)


@pytest.fixture
def shop(make_restaurant):
    return make_restaurant(name="Green Bowl", slug="green-bowl")


@pytest.fixture
def subscription(shop, plan):
    return services.start_trial(shop, plan)


# ---------- who may call ----------
def test_signed_out_gets_401_and_restaurant_owner_gets_403(api_client, make_user, make_restaurant, make_membership):
    assert api_client.get(f"{P}/me/").status_code == 401
    restaurant_owner = make_user()  # not a superuser
    make_membership(make_restaurant(), restaurant_owner, MembershipRole.OWNER)
    api_client.force_login(restaurant_owner)
    for path in ("me", "overview", "customers", "credentials", "plans", "subscriptions", "payments", "audit", "settings", "usage"):
        assert api_client.get(f"{P}/{path}/").status_code == 403, path


def test_inactive_superuser_cannot_call(api_client, owner):
    api_client.force_login(owner)
    owner.is_active = False
    owner.save()
    assert api_client.get(f"{P}/me/").status_code in (401, 403)


def test_owner_sees_identity(owner_client, owner):
    assert owner_client.get(f"{P}/me/").json()["user"]["email"] == owner.email


# ---------- plans ----------
def test_plan_create_edit_archive_are_validated_and_audited(owner_client):
    bad = owner_client.post(f"{P}/plans/", {"name": "x", "interval": "MONTHLY", "price": "-1", "included_requests": 1, "rate_limit_per_minute": 0}, format="json")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "validation_error"
    created = owner_client.post(f"{P}/plans/", {"name": "Growth", "interval": "YEARLY", "price": "30000", "included_requests": 100000, "rate_limit_per_minute": 120, "features": ["a", " ", "b"]}, format="json")
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "ACTIVE" and body["features"] == ["a", "b"] and body["currency"] == "NGN"
    assert owner_client.patch(f"{P}/plans/{body['id']}/", {"price": "35000.00"}, format="json").json()["price"] == "35000.00"
    assert owner_client.post(f"{P}/plans/{body['id']}/archive/").status_code == 204
    assert owner_client.post(f"{P}/plans/{body['id']}/archive/").status_code == 409
    assert owner_client.patch(f"{P}/plans/{body['id']}/", {"price": "1"}, format="json").status_code == 409
    assert list(PlatformAuditEvent.objects.order_by("id").values_list("action", flat=True)) == ["plan.created", "plan.updated", "plan.archived"]


# ---------- customers ----------
def test_customer_list_filters_and_detail(owner_client, shop, subscription, make_restaurant):
    make_restaurant(name="Other Place", slug="other-place", is_active=False)
    ApiUsageDaily.objects.create(restaurant=shop, date=timezone.localdate(), method="GET", path="/api/v1/x/", requests=40, errors=4)
    rows = owner_client.get(f"{P}/customers/", {"search": "green"}).json()["results"]
    assert [r["account_id"] for r in rows] == ["green-bowl"]
    assert rows[0]["requests_30d"] == 40 and rows[0]["plan"]["name"] == "Free trial" and rows[0]["next_plan"]["name"] == "Starter" and rows[0]["subscription_status"] == "TRIAL"
    assert [r["account_id"] for r in owner_client.get(f"{P}/customers/", {"status": "SUSPENDED"}).json()["results"]] == ["other-place"]
    assert owner_client.get(f"{P}/customers/", {"status": "nope"}).status_code == 400
    detail = owner_client.get(f"{P}/customers/{shop.pk}/").json()
    assert detail["usage"] == {"requests_30d": 40, "error_rate": 0.1} and "suspend" in detail["allowed_actions"] and "reactivate" not in detail["allowed_actions"]


def test_suspend_and_reactivate_change_the_restaurant_and_are_audited(owner_client, shop):
    assert owner_client.post(f"{P}/customers/{shop.pk}/suspend/").status_code == 204
    shop.refresh_from_db()
    assert shop.is_active is False
    assert owner_client.post(f"{P}/customers/{shop.pk}/suspend/").status_code == 409
    assert owner_client.post(f"{P}/customers/{shop.pk}/reactivate/").status_code == 204
    assert PlatformAuditEvent.objects.filter(action__in=["customer.suspended", "customer.reactivated"]).count() == 2


# ---------- credentials ----------
def test_credential_secret_is_shown_once_and_only_a_hash_is_stored(owner_client, shop, subscription):
    created = owner_client.post(f"{P}/credentials/", {"customer": "green-bowl", "name": "Website", "environment": "live"}, format="json")
    assert created.status_code == 201 and created.headers["Cache-Control"] == "no-store"
    secret = created.json()["secret"]
    stored = ApiCredential.objects.get()
    assert secret.startswith("sf_live_") and secret != stored.secret_hash and stored.secret_hash == services.hash_secret(secret)
    assert stored.rate_limit_per_minute is None and stored.monthly_request_limit is None  # follows the plan instead of copying it
    listing = owner_client.get(f"{P}/credentials/")
    assert secret not in listing.content.decode() and stored.secret_hash not in listing.content.decode()
    row = listing.json()["results"][0]
    assert row["allowed_actions"] == ["revoke"] and row["limits_source"] == "plan" and row["rate_limit_per_minute"] == 30  # the free trial plan's limit
    assert owner_client.post(f"{P}/credentials/{stored.pk}/revoke/").status_code == 204
    assert owner_client.post(f"{P}/credentials/{stored.pk}/revoke/").status_code == 409
    assert owner_client.get(f"{P}/credentials/").json()["results"][0]["allowed_actions"] == []


def test_credential_for_unknown_or_suspended_restaurant_is_rejected(owner_client, make_restaurant):
    make_restaurant(slug="closed-one", is_active=False)
    for slug in ("missing", "closed-one"):
        r = owner_client.post(f"{P}/credentials/", {"customer": slug, "name": "k", "environment": "test"}, format="json")
        assert r.status_code == 400 and "customer" in r.json()["error"]["details"]


# ---------- payments and subscriptions ----------
def _payment(subscription, amount="3000.00", reference="TRF-1"):
    return SubscriptionPayment.objects.create(subscription=subscription, reference=reference, amount=Decimal(amount), transacted_at=timezone.now())


def test_confirming_a_transfer_activates_and_extends_the_subscription(owner_client, subscription):
    payment = _payment(subscription)
    row = owner_client.get(f"{P}/payments/").json()["results"][0]
    assert row["status"] == "AWAITING_CONFIRMATION" and row["allowed_actions"] == ["confirm", "fail"]
    assert owner_client.post(f"{P}/payments/{payment.pk}/confirm/").status_code == 204
    subscription.refresh_from_db()
    payment.refresh_from_db()
    assert subscription.status == "ACTIVE" and payment.status == "CONFIRMED" and payment.confirmed_by is not None
    assert subscription.current_period_end - subscription.current_period_start >= timedelta(days=28)
    assert owner_client.post(f"{P}/payments/{payment.pk}/confirm/").status_code == 409  # never twice
    sub_row = owner_client.get(f"{P}/subscriptions/", {"status": "ACTIVE"}).json()["results"][0]
    assert sub_row["payment_status"] == "CONFIRMED" and sub_row["plan_name"] == "Starter"


def test_a_transfer_that_does_not_match_the_plan_price_is_refused(owner_client, subscription):
    payment = _payment(subscription, amount="2999.00")
    response = owner_client.post(f"{P}/payments/{payment.pk}/confirm/")
    assert response.status_code == 409 and response.json()["error"]["code"] == "amount_mismatch"
    payment.refresh_from_db()
    assert payment.status == "AWAITING_CONFIRMATION"


def test_an_ended_trial_expires_at_once_with_no_grace(subscription):
    now = timezone.now()
    Subscription.objects.update(current_period_end=now - timedelta(minutes=1))
    assert services.sync_lifecycle(now) == {"past_due": 0, "expired": 1}
    assert Subscription.objects.get().status == "EXPIRED"


def test_a_paid_subscription_gets_grace_days_before_it_expires(subscription):
    now = timezone.now()
    Subscription.objects.update(status="ACTIVE", current_period_end=now - timedelta(days=1))
    assert services.sync_lifecycle(now) == {"past_due": 1, "expired": 0}
    Subscription.objects.update(current_period_end=now - timedelta(days=10))
    assert services.sync_lifecycle(now) == {"past_due": 0, "expired": 1}
    assert Subscription.objects.get().status == "EXPIRED"


def test_start_trial_command_and_duplicate_refusal(shop, plan):
    call_command("start_trial", "green-bowl", plan="Starter", days=7)
    sub = Subscription.objects.get()
    assert sub.status == "TRIAL" and (sub.trial_ends_at - sub.started_at).days == 7
    with pytest.raises(Exception, match="already has a subscription"):
        call_command("start_trial", "green-bowl", plan="Starter")


# ---------- overview, usage, audit, settings ----------
def test_overview_with_no_data_reports_zeros_and_omits_what_it_cannot_know(owner_client):
    body = owner_client.get(f"{P}/overview/").json()
    assert body["totals"]["customers"] == 0 and body["totals"]["api_requests"] == 0
    assert "error_rate" not in body["totals"] and body["series"] == {"requests": [], "revenue": []}
    assert owner_client.get(f"{P}/overview/", {"range": "1y"}).status_code == 400


def test_overview_counts_real_rows(owner_client, subscription):
    payment = _payment(subscription)
    services.confirm_payment(payment.pk, None)
    ApiUsageDaily.objects.create(restaurant=subscription.restaurant, date=timezone.localdate(), method="GET", path="/p/", requests=100, errors=5)
    body = owner_client.get(f"{P}/overview/", {"range": "7d"}).json()
    assert body["totals"]["active_subscriptions"] == 1 and body["totals"]["mrr"] == {"amount": "3000.00", "currency": "NGN"}
    assert body["totals"]["api_requests"] == 100 and body["totals"]["error_rate"] == 0.05
    assert body["series"]["revenue"][0]["amount"] == "3000.00"
    assert body["subscription_status"]["ACTIVE"] == 1


def test_usage_validates_dates_and_groups_rows(owner_client, shop):
    today = timezone.localdate()
    ApiUsageDaily.objects.create(restaurant=shop, date=today, method="GET", path="/a/", requests=10, errors=1)
    body = owner_client.get(f"{P}/usage/").json()
    assert body["totals"] == {"requests": 10, "success": 9, "failed": 1, "error_rate": 0.1}
    assert body["by_customer"] == [{"name": "Green Bowl", "requests": 10, "errors": 1}] and body["by_endpoint"][0]["path"] == "/a/"
    assert owner_client.get(f"{P}/usage/", {"from": "2026-02-01", "to": "2026-01-01"}).status_code == 400
    assert owner_client.get(f"{P}/usage/", {"from": "garbage"}).status_code == 400


def test_audit_log_is_append_only_and_searchable(owner_client, owner):
    services.audit(owner, "plan.created", "plan", 1, "Starter")
    event = PlatformAuditEvent.objects.get()
    event.summary = "edited"
    with pytest.raises(RuntimeError):
        event.save()
    with pytest.raises(RuntimeError):
        event.delete()
    rows = owner_client.get(f"{P}/audit/", {"search": "starter"}).json()["results"]
    assert rows[0]["actor"] == owner.email and rows[0]["action"] == "plan.created"


def test_settings_endpoint_exposes_no_secrets(owner_client):
    body = owner_client.get(f"{P}/settings/").json()
    assert body["platform"]["trial_days"] == 2 and body["platform"]["grace_days"] == 3
    assert "secret" not in str(body).lower()


def test_writes_need_a_csrf_token(csrf_client, owner):
    csrf_client.force_login(owner)
    assert csrf_client.post(f"{P}/plans/", {"name": "x"}, format="json").status_code == 403
