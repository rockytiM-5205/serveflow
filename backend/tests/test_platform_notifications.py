"""The owner's notification bell."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.platform_admin import notifications, services
from apps.platform_admin.models import Plan, PlatformNotification, Subscription
from apps.restaurants.models import MembershipRole

P = "/api/v1/platform/notifications/"


@pytest.fixture
def owner_client(api_client, make_user):
    api_client.force_login(make_user(is_staff=True, is_superuser=True))
    return api_client


@pytest.fixture
def plan(db):
    return Plan.objects.create(name="Starter", interval="MONTHLY", price=Decimal("3000.00"), included_requests=1, rate_limit_per_minute=1)


@pytest.fixture
def shop(make_restaurant):
    return make_restaurant(name="Green Bowl", slug="green-bowl")


def test_only_the_platform_owner_sees_notifications(api_client, make_user):
    assert api_client.get(P).status_code == 401
    api_client.force_login(make_user())
    assert api_client.get(P).status_code == 403
    assert api_client.post(f"{P}read/", {}, format="json").status_code == 403


def test_notify_is_once_per_key_and_never_raises(shop):
    first = notifications.notify("signup", "Green Bowl signed up", restaurant=shop, dedupe_key="signup:1")
    again = notifications.notify("signup", "Green Bowl signed up", restaurant=shop, dedupe_key="signup:1")
    assert first is not None and again is None and PlatformNotification.objects.count() == 1
    assert notifications.notify("x", "y" * 500, "z" * 500, "#/a" * 100) is not None  # over-long text is trimmed, not an error


def test_summary_counts_unread_and_mark_read_works(owner_client):
    for i in range(3):
        notifications.notify("signup", f"R{i} signed up", dedupe_key=f"s{i}")
    body = owner_client.get(P).json()
    assert body["unread"] == 3 and len(body["results"]) == 3 and body["results"][0]["read"] is False
    first = body["results"][0]["id"]
    assert owner_client.post(f"{P}read/", {"ids": [first]}, format="json").json()["unread"] == 2
    assert owner_client.post(f"{P}read/", {}, format="json").json()["unread"] == 0
    assert owner_client.post(f"{P}read/", {"ids": "all"}, format="json").status_code == 400


def test_a_reported_transfer_notifies_the_owner_once(api_client, shop, plan, make_user, make_membership):
    from apps.platform_admin.models import PaymentDetails

    PaymentDetails.objects.create(bank_name="Opay", account_number="0123456789")
    admin = make_user()
    make_membership(shop, admin, MembershipRole.OWNER)
    services.start_trial(shop, plan)
    api_client.force_login(admin)
    url = f"/api/v1/restaurants/{shop.slug}/billing/payments/"
    api_client.post(url)
    api_client.post(url)  # asking again returns the same payment, so no second notification
    note = PlatformNotification.objects.get()
    assert note.kind == "payment_reported" and note.link == "#/payments" and "SF-" in note.detail and note.restaurant == shop


def test_signing_up_notifies_the_owner(settings, plan, make_restaurant, django_capture_on_commit_callbacks):
    settings.PLATFORM_AUTO_TRIAL = True
    with django_capture_on_commit_callbacks(execute=True):
        make_restaurant(name="Fresh", slug="fresh-place")
    assert PlatformNotification.objects.get().kind == "signup"


def test_sync_warns_before_a_trial_ends_and_when_it_locks_each_only_once(shop, plan):
    sub = services.start_trial(shop, plan)
    now = timezone.now()
    Subscription.objects.filter(pk=sub.pk).update(current_period_end=now + timedelta(hours=5))
    services.sync_lifecycle(now)
    services.sync_lifecycle(now)
    assert list(PlatformNotification.objects.values_list("kind", flat=True)) == ["trial_ending"]
    Subscription.objects.filter(pk=sub.pk).update(current_period_end=now - timedelta(minutes=1))
    services.sync_lifecycle(now)
    services.sync_lifecycle(now)
    assert sorted(PlatformNotification.objects.values_list("kind", flat=True)) == ["expired", "trial_ending"]


def test_deleting_a_restaurant_keeps_its_notifications(owner_client, shop, plan):
    notifications.notify("signup", "Green Bowl signed up", restaurant=shop, dedupe_key="s1")
    assert owner_client.delete(f"/api/v1/platform/customers/{shop.pk}/").status_code == 204
    assert PlatformNotification.objects.get().restaurant is None
