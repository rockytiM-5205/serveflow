"""Plans and payment instructions for newcomers, restaurant-side billing, and API key enforcement."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.platform_admin import services
from apps.platform_admin.models import (
    ApiCredential, ApiCredentialMonthlyUsage, PaymentDetails, Plan, PlatformAuditEvent, RateLimitEvent, Subscription,
    SubscriptionPayment,
)
from apps.restaurants.models import MembershipRole

PUBLIC = "/api/v1/restaurants/green-bowl/"
BILLING = f"{PUBLIC}billing/"
ACCOUNT = "0123456789"


@pytest.fixture(autouse=True)
def enabled(settings):
    settings.PLATFORM_ENFORCE_SUBSCRIPTIONS = True
    settings.PLATFORM_ENFORCE_API_KEYS = True
    settings.PLATFORM_METER_REQUESTS = True


@pytest.fixture
def shop(make_restaurant):
    return make_restaurant(name="Green Bowl", slug="green-bowl")


@pytest.fixture
def plan(db):
    return Plan.objects.create(name="Starter", interval="MONTHLY", price=Decimal("3000.00"), included_requests=10000, rate_limit_per_minute=60)


@pytest.fixture
def details(db):
    return PaymentDetails.objects.create(bank_name="Example Bank", account_name="ServeFlow Ltd", account_number=ACCOUNT, instructions="Use your reference as the narration.")


@pytest.fixture
def owner_client(api_client, make_user, make_membership, shop):
    make_membership(shop, make_user(), MembershipRole.OWNER)
    api_client.force_login(shop.memberships.first().user)
    return api_client


# ---------- newcomers: plans and how to pay ----------
def test_anyone_can_see_active_plans_and_the_payment_method_but_not_account_numbers(api_client, plan, details):
    Plan.objects.create(name="Old", interval="MONTHLY", price=Decimal("1.00"), included_requests=1, rate_limit_per_minute=1, status="ARCHIVED")
    response = api_client.get("/api/v1/billing/plans/")
    body = response.json()
    assert response.status_code == 200 and [p["name"] for p in body["plans"]] == ["Starter"]
    assert body["payment"] == {"method": "BANK_TRANSFER", "ready": True, "instructions": "Use your reference as the narration."}
    assert ACCOUNT not in response.content.decode() and "Example Bank" not in response.content.decode()


def test_with_no_plans_or_details_the_public_page_data_is_honestly_empty(api_client):
    body = api_client.get("/api/v1/billing/plans/").json()
    assert body["plans"] == [] and body["payment"]["ready"] is False


# ---------- restaurant owner: choose, pay, report ----------
def test_only_the_restaurant_owner_can_use_billing(api_client, make_user, make_membership, shop, plan):
    assert api_client.get(BILLING).status_code == 401
    manager = make_user()
    make_membership(shop, manager, MembershipRole.MANAGER)
    api_client.force_login(manager)
    assert api_client.get(BILLING).status_code == 403
    assert api_client.post(f"{BILLING}subscribe/", {"plan_id": plan.pk}, format="json").status_code == 403


def test_choosing_a_plan_starts_the_trial_and_shows_the_bank_details_to_the_owner(owner_client, shop, plan, details):
    body = owner_client.get(BILLING).json()
    assert body["subscription"] is None and [p["id"] for p in body["plans"]] == [plan.pk]
    assert body["payment_details"]["account_number"] == ACCOUNT
    started = owner_client.post(f"{BILLING}subscribe/", {"plan_id": plan.pk}, format="json")
    assert started.status_code == 201 and started.json()["subscription"]["status"] == "TRIAL"
    assert owner_client.post(f"{BILLING}subscribe/", {"plan_id": 999999}, format="json").status_code == 400
    assert owner_client.post(f"{BILLING}subscribe/", {"plan_id": "x"}, format="json").status_code == 400


def test_a_trial_can_switch_plan_before_paying(owner_client, shop, plan):
    other = Plan.objects.create(name="Growth", interval="MONTHLY", price=Decimal("9000.00"), included_requests=1, rate_limit_per_minute=5)
    services.start_trial(shop, plan)
    switched = owner_client.post(f"{BILLING}subscribe/", {"plan_id": other.pk}, format="json").json()["subscription"]
    assert switched["plan"]["name"] == "Free trial" and switched["next_plan"]["name"] == "Growth" and switched["plan_to_pay"]["name"] == "Growth"


def test_reporting_a_transfer_gives_one_reference_and_the_owner_confirms_it(owner_client, shop, plan, details):
    owner_client.post(f"{BILLING}subscribe/", {"plan_id": plan.pk}, format="json")
    first = owner_client.post(f"{BILLING}payments/")
    again = owner_client.post(f"{BILLING}payments/")
    assert first.status_code == 201 and again.status_code == 200
    reference = first.json()["payment"]["reference"]
    assert reference.startswith("SF-") and again.json()["payment"]["reference"] == reference
    assert owner_client.get(BILLING).json()["open_payment"]["reference"] == reference
    payment = SubscriptionPayment.objects.get()
    assert payment.amount == plan.price and payment.status == "AWAITING_CONFIRMATION"
    services.confirm_payment(payment.pk, None)
    assert Subscription.objects.get().status == "ACTIVE"
    assert owner_client.get(BILLING).json()["open_payment"] is None


def test_paying_needs_a_plan_and_published_bank_details(owner_client, shop, plan, details):
    assert owner_client.post(f"{BILLING}payments/").json()["error"]["code"] == "no_subscription"
    details.delete()
    services.start_trial(shop, plan)
    assert owner_client.post(f"{BILLING}payments/").json()["error"]["code"] == "payment_details_missing"


def test_an_expired_restaurant_can_still_see_its_plan_and_pay(api_client, owner_client, shop, plan, details):
    sub = services.start_trial(shop, plan)
    Subscription.objects.filter(pk=sub.pk).update(status="EXPIRED", current_period_end=timezone.now() - timedelta(days=30))
    assert owner_client.get(BILLING).status_code == 200
    assert owner_client.post(f"{BILLING}payments/").status_code == 201
    assert owner_client.patch(f"{PUBLIC}settings/", {"accepting_orders": True}, format="json").status_code == 402  # everything else stays locked


# ---------- platform owner edits payment details ----------
def test_platform_owner_sets_payment_details_and_the_audit_log_omits_the_number(api_client, make_user):
    api_client.force_login(make_user(is_staff=True, is_superuser=True))
    bad = api_client.patch("/api/v1/platform/settings/", {"account_number": "12ab"}, format="json")
    assert bad.status_code == 400
    ok = api_client.patch("/api/v1/platform/settings/", {"bank_name": "Example Bank", "account_name": "ServeFlow Ltd", "account_number": ACCOUNT}, format="json")
    assert ok.status_code == 200 and ok.json()["payment_details"]["account_number"] == ACCOUNT
    assert api_client.get("/api/v1/billing/plans/").json()["payment"]["ready"] is True
    assert not PlatformAuditEvent.objects.filter(summary__contains=ACCOUNT).exists()


# ---------- API keys ----------
def _key(shop, environment="live", **limits):
    credential, secret = services.create_credential(actor=None, customer=shop, name="Website", environment=environment, **limits)
    return credential, {"HTTP_AUTHORIZATION": f"Bearer {secret}"}


def test_a_valid_key_works_and_is_counted(api_client, shop):
    credential, auth = _key(shop)
    assert api_client.get(PUBLIC, **auth).status_code == 200
    credential.refresh_from_db()
    assert credential.last_used_at is not None
    assert ApiCredentialMonthlyUsage.objects.get(credential=credential).requests == 1


def test_requests_without_a_key_or_with_another_bearer_scheme_are_unchanged(api_client, shop):
    assert api_client.get(PUBLIC).status_code == 200
    assert api_client.get(PUBLIC, HTTP_AUTHORIZATION="Bearer not-a-serveflow-key").status_code == 200


def test_unknown_revoked_and_foreign_keys_are_refused(api_client, shop, make_restaurant):
    credential, auth = _key(shop)
    assert api_client.get(PUBLIC, HTTP_AUTHORIZATION="Bearer sf_live_nope").json()["error"]["code"] == "invalid_api_key"
    other = make_restaurant(name="Other", slug="other-place")
    assert api_client.get("/api/v1/restaurants/other-place/", **auth).json()["error"]["code"] == "api_key_wrong_restaurant"
    assert api_client.get(PUBLIC, **auth).status_code == 200  # cached as valid ...
    services.revoke_credential(credential.pk, None)
    response = api_client.get(PUBLIC, **auth)  # ... and revocation still takes effect at once
    assert response.status_code == 401 and response.json()["error"]["code"] == "invalid_api_key"
    assert other.pk != shop.pk


def test_test_keys_can_read_but_not_write(api_client, shop):
    _, auth = _key(shop, environment="test")
    assert api_client.get(PUBLIC, **auth).status_code == 200
    blocked = api_client.post(f"{PUBLIC}checkout/", {}, format="json", **auth)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "test_key_read_only"


def test_the_per_minute_limit_returns_429_and_logs_one_event(api_client, shop):
    credential, auth = _key(shop, rate_limit_per_minute=2)
    assert [api_client.get(PUBLIC, **auth).status_code for _ in range(2)] == [200, 200]
    limited = api_client.get(PUBLIC, **auth)
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited" and int(limited.headers["Retry-After"]) >= 1
    event = RateLimitEvent.objects.get()  # exactly one, not a second generic "throttled" row
    assert event.credential == credential and event.limit == "2/min"


def test_the_monthly_allowance_is_enforced(api_client, shop):
    _, auth = _key(shop, monthly_request_limit=1)
    assert api_client.get(PUBLIC, **auth).status_code == 200
    over = api_client.get(PUBLIC, **auth)
    assert over.status_code == 429 and over.json()["error"]["code"] == "monthly_quota_exceeded"


def test_a_key_does_not_bypass_the_subscription_lock(api_client, shop, plan):
    now = timezone.now()
    Subscription.objects.create(restaurant=shop, plan=plan, status="EXPIRED", started_at=now, current_period_start=now, current_period_end=now)
    _, auth = _key(shop)
    assert api_client.get(PUBLIC, **auth).status_code == 402


def test_a_key_without_its_own_numbers_follows_the_restaurants_current_plan(shop, plan):
    from apps.platform_admin import apikeys

    services.start_trial(shop, plan)  # on the free trial plan (30 per minute, 5,000 a month to start with)
    credential, secret = services.create_credential(actor=None, customer=shop, name="Website", environment="live")
    assert credential.rate_limit_per_minute is None and ApiCredential.objects.count() == 1
    state = apikeys._lookup(secret)
    assert (state["rate_limit_per_minute"], state["monthly_request_limit"]) == (30, 5000)
    free = services.trial_plan()
    free.rate_limit_per_minute, free.included_requests = 7, 123
    free.save()
    apikeys.forget(credential.secret_hash)  # the 30 second cache would otherwise hide the edit
    state = apikeys._lookup(secret)
    assert (state["rate_limit_per_minute"], state["monthly_request_limit"]) == (7, 123)
    own, own_secret = services.create_credential(actor=None, customer=shop, name="Custom", environment="live", rate_limit_per_minute=2)
    assert apikeys._lookup(own_secret)["rate_limit_per_minute"] == 2 and own.rate_limit_per_minute == 2


# ---------- trial at sign-up, and the payment command ----------
def test_a_new_restaurant_starts_a_two_day_trial_on_the_free_plan(settings, plan, make_restaurant, django_capture_on_commit_callbacks):
    settings.PLATFORM_AUTO_TRIAL = True
    with django_capture_on_commit_callbacks(execute=True):
        fresh = make_restaurant(name="Fresh", slug="fresh-place")
    sub = Subscription.objects.get(restaurant=fresh)
    assert sub.status == "TRIAL" and sub.plan.is_trial and sub.plan.name == "Free trial" and sub.next_plan is None
    assert (sub.trial_ends_at - sub.started_at) == timedelta(days=2) and sub.plan.price == 0


def test_the_trial_starts_even_before_any_paid_plan_exists(settings, make_restaurant, django_capture_on_commit_callbacks):
    settings.PLATFORM_AUTO_TRIAL = True
    with django_capture_on_commit_callbacks(execute=True):
        make_restaurant(name="Early", slug="early-bird")
    assert Subscription.objects.get().plan.is_trial


def test_paying_requires_choosing_a_paid_plan_first(owner_client, shop, details):
    services.start_trial(shop)  # on the free trial, nothing chosen yet
    refused = owner_client.post(f"{BILLING}payments/")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "no_plan_chosen"


def test_the_free_plan_is_not_for_sale_and_cannot_be_archived_or_repriced(api_client, make_user, plan):
    free = services.trial_plan()
    public = api_client.get("/api/v1/billing/plans/").json()["plans"]
    assert [p["name"] for p in public] == ["Starter"]
    api_client.force_login(make_user(is_staff=True, is_superuser=True))
    assert any(p["is_trial"] for p in api_client.get("/api/v1/platform/plans/").json()["results"])
    assert api_client.post(f"/api/v1/platform/plans/{free.pk}/archive/").json()["error"]["code"] == "trial_plan"
    assert api_client.patch(f"/api/v1/platform/plans/{free.pk}/", {"price": "5"}, format="json").status_code == 400
    edited = api_client.patch(f"/api/v1/platform/plans/{free.pk}/", {"included_requests": 8000, "rate_limit_per_minute": 40}, format="json")
    assert edited.status_code == 200 and edited.json()["included_requests"] == 8000


def test_paying_moves_the_restaurant_from_the_free_plan_onto_the_paid_one(owner_client, shop, plan, details):
    owner_client.post(f"{BILLING}subscribe/", {"plan_id": plan.pk}, format="json")
    assert Subscription.objects.get().plan.is_trial
    owner_client.post(f"{BILLING}payments/")
    services.confirm_payment(SubscriptionPayment.objects.get().pk, None)
    sub = Subscription.objects.get()
    assert sub.plan == plan and sub.next_plan is None and sub.status == "ACTIVE"


def test_a_restaurant_stops_working_when_its_trial_ends_and_works_again_after_payment(api_client, shop, plan, details):
    sub = services.start_trial(shop, plan)
    assert api_client.get(PUBLIC).status_code != 402
    Subscription.objects.filter(pk=sub.pk).update(current_period_end=timezone.now() - timedelta(minutes=1))
    from apps.platform_admin import locks
    locks.forget("green-bowl")
    assert api_client.get(PUBLIC).status_code == 402
    payment = SubscriptionPayment.objects.create(subscription=sub, reference="TRF-1", amount=plan.price, transacted_at=timezone.now())
    services.confirm_payment(payment.pk, None)
    assert api_client.get(PUBLIC).status_code != 402


def test_payment_details_command_sets_the_account_and_does_not_need_an_account_name(api_client):
    from django.core.management import call_command

    call_command("set_payment_details", bank="Opay", account_number=ACCOUNT)
    details = PaymentDetails.objects.get()
    assert details.ready and details.account_name == ""
    assert api_client.get("/api/v1/billing/plans/").json()["payment"]["ready"] is True
    with pytest.raises(Exception, match="6 to 20 digits"):
        call_command("set_payment_details", bank="Opay", account_number="12ab")
