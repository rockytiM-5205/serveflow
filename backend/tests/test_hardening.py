"""Security hardening: admin lockout, trusted client address, capacity reservation, push address checks, marketplace approval."""
import pytest
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.common.throttles import client_ip


# ---------------------------------------------------------------- admin login lockout
@pytest.mark.django_db
def test_admin_login_locks_after_repeated_failures_even_for_the_right_password(settings):
    settings.ADMIN_LOCKOUT_FAILURES = 3
    User.objects.create_superuser(email="owner@example.com", password="correct-horse-battery-1")
    client, login = APIClient(), reverse("admin:login")
    for _ in range(3):
        assert client.post(login, {"username": "owner@example.com", "password": "wrong"}).status_code == 200  # form redisplayed
    assert client.post(login, {"username": "owner@example.com", "password": "wrong"}).status_code == 429
    assert client.post(login, {"username": "owner@example.com", "password": "correct-horse-battery-1"}).status_code == 429


@pytest.mark.django_db
def test_admin_login_still_works_before_the_limit_and_resets_on_success(settings):
    settings.ADMIN_LOCKOUT_FAILURES = 3
    User.objects.create_superuser(email="owner@example.com", password="correct-horse-battery-1")
    client, login = APIClient(), reverse("admin:login")
    for _ in range(2):
        client.post(login, {"username": "owner@example.com", "password": "wrong"})
    ok = client.post(login, {"username": "owner@example.com", "password": "correct-horse-battery-1"})
    assert ok.status_code == 302  # signed in, counter cleared


# ---------------------------------------------------------------- the client address cannot be chosen by the client
def _request(forwarded=None, remote="10.0.0.9"):
    extra = {"REMOTE_ADDR": remote}
    if forwarded:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded
    return RequestFactory().get("/", **extra)


def test_forwarded_header_is_ignored_when_no_proxy_is_configured(settings):
    settings.TRUSTED_PROXY_COUNT = 0
    assert client_ip(_request("1.2.3.4")) == "10.0.0.9"
    assert client_ip(_request("5.6.7.8")) == "10.0.0.9"  # a different forged value does not give a fresh identity


def test_only_the_entries_our_proxies_added_are_trusted(settings):
    settings.TRUSTED_PROXY_COUNT = 2  # Vercel then Render
    assert client_ip(_request("203.0.113.7, 76.76.21.1")) == "203.0.113.7"
    assert client_ip(_request("forged, 203.0.113.7, 76.76.21.1")) == "203.0.113.7"  # what the client prepended is ignored
    settings.TRUSTED_PROXY_COUNT = 1
    assert client_ip(_request("203.0.113.7, 76.76.21.1")) == "76.76.21.1"


@pytest.mark.django_db
def test_login_limit_cannot_be_reset_with_a_forged_forwarded_header(settings):
    settings.TRUSTED_PROXY_COUNT = 0
    client, url = APIClient(), reverse("auth-login")
    for n in range(5):
        client.post(url, {"email": f"nobody{n}@example.com", "password": "x" * 10}, format="json", HTTP_X_FORWARDED_FOR=f"9.9.9.{n}")
    blocked = client.post(url, {"email": "nobody9@example.com", "password": "x" * 10}, format="json", HTTP_X_FORWARDED_FOR="9.9.9.99")
    assert blocked.status_code == 429


# ---------------------------------------------------------------- marketplace approval and bank-detail notices
from apps.orders.models import PaymentStatus  # noqa: E402,F401
from apps.platform_admin.models import PlatformNotification  # noqa: E402
from apps.restaurants.models import MembershipRole, Restaurant  # noqa: E402


def _search(client):
    return [r["slug"] for r in client.get(reverse("marketplace-restaurants")).json()["results"]]


@pytest.mark.django_db
def test_a_restaurant_that_lists_itself_is_not_shown_until_the_platform_owner_approves(api_client, shop, staff_login, make_user):
    Restaurant.objects.filter(pk=shop.restaurant.pk).update(listed_in_marketplace=True, area="Akungba")
    assert shop.restaurant.slug not in _search(APIClient())  # switched on by the restaurant, but not approved
    api_client.force_login(make_user(is_staff=True, is_superuser=True))
    approve = reverse("platform-customer-marketplace", kwargs={"pk": shop.restaurant.pk})
    assert api_client.post(approve, {"approved": True}, format="json").status_code == 200
    assert shop.restaurant.slug in _search(APIClient())
    assert api_client.post(approve, {"approved": False}, format="json").status_code == 200
    assert shop.restaurant.slug not in _search(APIClient())
    assert api_client.post(approve, {"approved": "yes"}, format="json").status_code == 400


@pytest.mark.django_db
def test_a_restaurant_owner_cannot_approve_itself(api_client, shop, staff_login):
    staff_login(shop.restaurant, MembershipRole.OWNER)
    assert api_client.post(reverse("platform-customer-marketplace", kwargs={"pk": shop.restaurant.pk}), {"approved": True}, format="json").status_code == 403
    settings_url = reverse("restaurant-settings", kwargs={"slug": shop.restaurant.slug})
    api_client.patch(settings_url, {"marketplace_approved": True}, format="json")  # a read-only field: ignored
    shop.restaurant.refresh_from_db()
    assert shop.restaurant.marketplace_approved is False


@pytest.mark.django_db
def test_listing_request_and_bank_detail_changes_notify_the_platform_owner(api_client, shop, staff_login):
    staff_login(shop.restaurant, MembershipRole.OWNER)
    settings_url = reverse("restaurant-settings", kwargs={"slug": shop.restaurant.slug})
    response = api_client.patch(settings_url, {"listed_in_marketplace": True, "area": "Akungba"}, format="json")
    assert response.status_code == 200 and response.json()["marketplace_approved"] is False
    assert PlatformNotification.objects.filter(kind="marketplace_review", restaurant=shop.restaurant).count() == 1
    account = reverse("restaurant-payment-account", kwargs={"slug": shop.restaurant.slug})
    body = {"bank_name": "First Bank", "account_name": "New Name", "account_number": "0123456789", "instructions": ""}
    api_client.put(account, body, format="json")
    assert PlatformNotification.objects.filter(kind="payment_account_changed", restaurant=shop.restaurant).count() == 1
