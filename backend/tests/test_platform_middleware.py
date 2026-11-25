"""Subscription lock and request metering (apps/platform_admin/middleware.py). Both are off in the test settings,
so every test here switches on what it needs."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.platform_admin import services
from apps.platform_admin.models import ApiUsageDaily, Plan, RateLimitEvent, Subscription, SubscriptionPayment
from apps.restaurants.models import MembershipRole

PUBLIC = "/api/v1/restaurants/green-bowl/"
SETTINGS = f"{PUBLIC}settings/"


@pytest.fixture(autouse=True)
def enabled(settings):
    settings.PLATFORM_ENFORCE_SUBSCRIPTIONS = True
    settings.PLATFORM_METER_REQUESTS = True


@pytest.fixture
def shop(make_restaurant):
    return make_restaurant(name="Green Bowl", slug="green-bowl")


@pytest.fixture
def plan(db):
    return Plan.objects.create(name="Starter", interval="MONTHLY", price=Decimal("3000.00"), included_requests=10000, rate_limit_per_minute=60)


def _subscribe(shop, plan, status, ends_in=timedelta(days=-10)):
    now = timezone.now()
    return Subscription.objects.create(restaurant=shop, plan=plan, status=status, started_at=now - timedelta(days=60),
                                       current_period_start=now - timedelta(days=30), current_period_end=now + ends_in)


def _staff(api_client, make_user, make_membership, shop, role=MembershipRole.OWNER):
    user = make_user()
    make_membership(shop, user, role)
    api_client.force_login(user)
    return user


# ---------- lock ----------
@pytest.mark.parametrize("status", [Subscription.Status.EXPIRED, Subscription.Status.CANCELLED])
def test_customers_get_402_when_the_subscription_has_ended(api_client, shop, plan, status):
    _subscribe(shop, plan, status)
    response = api_client.get(PUBLIC)
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "subscription_inactive"


@pytest.mark.parametrize("status, ends_in", [
    (Subscription.Status.TRIAL, timedelta(hours=1)),
    (Subscription.Status.ACTIVE, timedelta(days=5)),
    (Subscription.Status.PAST_DUE, timedelta(days=-1)),  # inside the 3 grace days
])
def test_running_trials_paid_subscriptions_and_the_grace_period_are_not_locked(api_client, shop, plan, status, ends_in):
    _subscribe(shop, plan, status, ends_in)
    assert api_client.get(PUBLIC).status_code != 402


def test_a_trial_locks_the_moment_it_ends_even_before_the_sync_runs(api_client, shop, plan):
    _subscribe(shop, plan, Subscription.Status.TRIAL, timedelta(minutes=-1))  # still stored as TRIAL
    assert api_client.get(PUBLIC).status_code == 402


@pytest.mark.parametrize("days_ago, locked", [(2, False), (4, True)])
def test_a_paid_subscription_locks_only_after_the_grace_days(api_client, shop, plan, days_ago, locked):
    _subscribe(shop, plan, Subscription.Status.ACTIVE, timedelta(days=-days_ago))
    assert (api_client.get(PUBLIC).status_code == 402) is locked


def test_a_restaurant_with_no_subscription_is_never_locked(api_client, shop):
    assert api_client.get(PUBLIC).status_code != 402


def test_staff_of_a_locked_restaurant_can_read_but_not_change(api_client, make_user, make_membership, shop, plan):
    _subscribe(shop, plan, Subscription.Status.EXPIRED)
    _staff(api_client, make_user, make_membership, shop)
    assert api_client.get(SETTINGS).status_code != 402
    blocked = api_client.patch(SETTINGS, {"accepting_orders": True}, format="json")
    assert blocked.status_code == 402 and "subscription has ended" in blocked.json()["error"]["message"]


def test_platform_owner_is_exempt(api_client, make_user, shop, plan):
    _subscribe(shop, plan, Subscription.Status.EXPIRED)
    api_client.force_login(make_user(is_staff=True, is_superuser=True))
    assert api_client.get(PUBLIC).status_code != 402


def test_confirming_a_payment_unlocks_the_restaurant_immediately(api_client, shop, plan):
    subscription = _subscribe(shop, plan, Subscription.Status.EXPIRED)
    assert api_client.get(PUBLIC).status_code == 402  # state is now cached
    payment = SubscriptionPayment.objects.create(subscription=subscription, reference="TRF-9", amount=plan.price, transacted_at=timezone.now())
    services.confirm_payment(payment.pk, None)
    assert api_client.get(PUBLIC).status_code != 402


def test_switching_enforcement_off_lets_everything_through(api_client, shop, plan, settings):
    _subscribe(shop, plan, Subscription.Status.EXPIRED)
    settings.PLATFORM_ENFORCE_SUBSCRIPTIONS = False
    assert api_client.get(PUBLIC).status_code != 402


# ---------- metering ----------
def test_requests_are_counted_per_restaurant_day_and_route(api_client, shop):
    for _ in range(3):
        api_client.get(PUBLIC)
    row = ApiUsageDaily.objects.get()
    assert row.restaurant == shop and row.requests == 3 and row.errors == 0 and row.method == "GET"
    assert "<slug:slug>" in row.path  # a route pattern, never the raw URL
    assert "green-bowl" not in row.path


def test_locked_requests_are_counted_too(api_client, shop, plan):
    _subscribe(shop, plan, Subscription.Status.EXPIRED)
    api_client.get(PUBLIC)
    assert ApiUsageDaily.objects.get().requests == 1


def test_unknown_restaurants_and_unknown_routes_record_nothing(api_client, shop):
    api_client.get("/api/v1/restaurants/no-such-place/")
    api_client.get("/api/v1/nope/")
    assert ApiUsageDaily.objects.count() == 0


def test_record_usage_is_an_atomic_upsert_and_counts_only_server_errors(shop):
    day = timezone.localdate()
    services.record_usage(shop.pk, "GET", "/p/", day=day)
    services.record_usage(shop.pk, "GET", "/p/", error=True, day=day)
    row = ApiUsageDaily.objects.get()
    assert (row.requests, row.errors) == (2, 1)


def test_a_metering_failure_never_breaks_the_response(api_client, shop, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(services, "record_usage", boom)
    assert api_client.get(PUBLIC).status_code != 500


def test_throttled_responses_create_a_rate_limit_event(shop):
    services.record_rate_limit_event(shop.pk, "/api/v1/restaurants/<slug:slug>/checkout/", "throttled")
    assert RateLimitEvent.objects.get().endpoint.endswith("checkout/")
