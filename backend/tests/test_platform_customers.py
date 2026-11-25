"""The platform owner creates and manages restaurant accounts, each with exactly one admin."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from apps.platform_admin import services
from apps.platform_admin.models import Plan, PlatformAuditEvent, Subscription, SubscriptionPayment
from apps.restaurants.models import MembershipRole, Restaurant, RestaurantMembership
from apps.restaurants.services import can_create_restaurant

P = "/api/v1/platform/customers/"
STRONG = "a-long-unusual-pass-9"
BODY = {"name": "Green Bowl", "slug": "green-bowl", "currency": "NGN", "timezone": "Africa/Lagos", "admin_email": "Chef@Example.com", "admin_first_name": "Ada"}


@pytest.fixture
def owner_client(api_client, make_user):
    api_client.force_login(make_user(is_staff=True, is_superuser=True))
    return api_client


@pytest.fixture
def plans(db):
    cheap = Plan.objects.create(name="Starter", interval="MONTHLY", price=Decimal("3000.00"), included_requests=1, rate_limit_per_minute=1)
    dear = Plan.objects.create(name="Growth", interval="MONTHLY", price=Decimal("9000.00"), included_requests=1, rate_limit_per_minute=1)
    return cheap, dear


def create(client, **extra):
    return client.post(P, {**BODY, **extra}, format="json")


# ---------- creating a restaurant with its admin ----------
def test_creating_a_restaurant_also_creates_its_one_admin_and_starts_one_trial(settings, owner_client, plans, django_capture_on_commit_callbacks):
    settings.PLATFORM_AUTO_TRIAL = True  # the auto-trial must not double up with the owner's own
    with django_capture_on_commit_callbacks(execute=True):
        response = create(owner_client)
    assert response.status_code == 201 and response.headers["Cache-Control"] == "no-store"
    body = response.json()
    restaurant = Restaurant.objects.get(slug="green-bowl")
    admin = get_user_model().objects.get(email="chef@example.com")
    assert body["admin_email"] == "chef@example.com" and body["customer"]["admin"]["email"] == "chef@example.com"
    assert admin.check_password(body["temporary_password"]) and admin.first_name == "Ada"
    assert list(RestaurantMembership.objects.filter(restaurant=restaurant).values_list("role", flat=True)) == ["OWNER"]
    sub = Subscription.objects.get(restaurant=restaurant)
    assert Subscription.objects.filter(restaurant=restaurant).count() == 1 and sub.plan.is_trial and sub.next_plan is None
    assert body["trial_started"] is True and restaurant.accepting_orders is False
    event = PlatformAuditEvent.objects.get(action="customer.created")
    assert "chef@example.com" not in event.summary


def test_owner_can_choose_the_plan_set_the_password_or_skip_the_trial(owner_client, plans):
    r = create(owner_client, plan_id=plans[1].pk, admin_password=STRONG)
    assert r.status_code == 201 and r.json()["temporary_password"] is None
    assert get_user_model().objects.get(email="chef@example.com").check_password(STRONG)
    assert Subscription.objects.get().plan.is_trial and Subscription.objects.get().next_plan == plans[1]
    skipped = create(owner_client, slug="no-trial-place", admin_email="other@example.com", start_trial=False)
    assert skipped.json()["trial_started"] is False and Subscription.objects.count() == 1


def test_one_admin_one_restaurant(owner_client, make_user, make_restaurant, make_membership):
    busy = make_user(email="busy@example.com")
    make_membership(make_restaurant(), busy, MembershipRole.OWNER)
    refused = create(owner_client, admin_email="busy@example.com")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "admin_has_restaurant"
    assert not Restaurant.objects.filter(slug="green-bowl").exists()  # nothing half-created
    boss = make_user(email="boss@example.com", is_staff=True, is_superuser=True)
    assert create(owner_client, admin_email=boss.email).json()["error"]["code"] == "admin_is_platform_owner"
    free = make_user(email="free@example.com")
    assert create(owner_client, admin_email=free.email).status_code == 201  # an existing account with no restaurant is attached
    assert RestaurantMembership.objects.get(user=free).role == "OWNER"


def test_creation_is_validated_and_owner_only(owner_client, api_client, make_user):
    assert create(owner_client, slug="Bad Slug!").status_code == 400
    assert create(owner_client, slug="ab").status_code == 400  # too short
    assert create(owner_client, admin_email="nope").status_code == 400
    assert create(owner_client, admin_password="123").status_code == 400
    assert not Restaurant.objects.exists() and not get_user_model().objects.filter(email="chef@example.com").exists()
    api_client.force_login(make_user())
    assert create(api_client).status_code == 403


# ---------- editing ----------
def test_owner_edits_the_restaurant_and_its_admin_but_never_the_account_id(owner_client, plans):
    created = create(owner_client).json()["customer"]
    url = f"{P}{created['id']}/"
    ok = owner_client.patch(url, {"name": "Green Bowl 2", "slug": "hacked", "address": "1 Allen Ave", "admin": {"first_name": "Bola", "email": "bola@example.com"}}, format="json")
    assert ok.status_code == 200
    body = ok.json()
    assert body["name"] == "Green Bowl 2" and body["account_id"] == "green-bowl" and body["address"] == "1 Allen Ave"
    assert body["admin"]["email"] == "bola@example.com" and body["admin"]["first_name"] == "Bola"
    get_user_model().objects.create_user("taken@example.com", STRONG)
    assert owner_client.patch(url, {"admin": {"email": "taken@example.com"}}, format="json").json()["error"]["code"] == "email_taken"


def test_resetting_the_admin_password_gives_a_new_one_once(owner_client, plans):
    created = create(owner_client, admin_password=STRONG).json()["customer"]
    response = owner_client.post(f"{P}{created['id']}/reset-admin-password/")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    admin = get_user_model().objects.get(email="chef@example.com")
    assert admin.check_password(response.json()["temporary_password"]) and not admin.check_password(STRONG)


# ---------- time and plan ----------
def test_extending_gives_an_expired_restaurant_time_again(owner_client, plans):
    created = create(owner_client).json()["customer"]
    Subscription.objects.update(status="EXPIRED", current_period_end=timezone.now() - timedelta(days=3))
    assert owner_client.post(f"{P}{created['id']}/extend/", {"days": 0}, format="json").status_code == 400
    ok = owner_client.post(f"{P}{created['id']}/extend/", {"days": 5, "reason": "goodwill"}, format="json")
    assert ok.status_code == 200 and ok.json()["subscription"]["status"] == "TRIAL"
    assert Subscription.objects.get().current_period_end > timezone.now() + timedelta(days=4)


def test_changing_the_plan_and_starting_one_when_there_is_none(owner_client, plans):
    first = create(owner_client, start_trial=False).json()["customer"]
    assert first["subscription"] is None
    changed = owner_client.post(f"{P}{first['id']}/plan/", {"plan_id": plans[1].pk}, format="json").json()
    assert changed["subscription"]["plan"]["name"] == "Free trial" and changed["subscription"]["next_plan"]["name"] == "Growth" and changed["subscription"]["status"] == "TRIAL"
    assert owner_client.post(f"{P}{first['id']}/plan/", {"plan_id": plans[0].pk}, format="json").json()["subscription"]["next_plan"]["name"] == "Starter"
    Subscription.objects.update(status="ACTIVE")  # a paying restaurant moves onto the new plan at once
    assert owner_client.post(f"{P}{first['id']}/plan/", {"plan_id": plans[1].pk}, format="json").json()["subscription"]["plan"]["name"] == "Growth"
    assert owner_client.post(f"{P}{first['id']}/plan/", {"plan_id": 999}, format="json").status_code == 400
    assert owner_client.post(f"{P}{first['id']}/plan/", {"plan_id": services.trial_plan().pk}, format="json").status_code == 409


# ---------- deleting ----------
def test_an_empty_restaurant_can_be_deleted_and_its_admin_is_switched_off(owner_client, plans):
    created = create(owner_client).json()["customer"]
    assert owner_client.delete(f"{P}{created['id']}/").status_code == 204
    assert not Restaurant.objects.exists()
    assert get_user_model().objects.get(email="chef@example.com").is_active is False


def test_a_restaurant_with_history_cannot_be_deleted_only_suspended(owner_client, plans, make_category):
    created = create(owner_client).json()["customer"]
    restaurant = Restaurant.objects.get(pk=created["id"])
    make_category(restaurant)
    refused = owner_client.delete(f"{P}{created['id']}/")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "customer_has_history"
    assert Restaurant.objects.filter(pk=restaurant.pk).exists() and Subscription.objects.filter(restaurant=restaurant).exists()  # rolled back whole
    assert owner_client.post(f"{P}{created['id']}/suspend/").status_code == 204


def test_a_restaurant_with_payments_cannot_be_deleted(owner_client, plans):
    created = create(owner_client).json()["customer"]
    SubscriptionPayment.objects.create(subscription=Subscription.objects.get(), reference="TRF-1", amount=Decimal("3000"), transacted_at=timezone.now())
    assert owner_client.delete(f"{P}{created['id']}/").status_code == 409


# ---------- the one-admin rule and one restaurant per account ----------
def test_restaurant_admins_cannot_add_or_promote_a_second_owner(api_client, make_user, make_restaurant, make_membership):
    restaurant = make_restaurant()
    admin = make_user()
    make_membership(restaurant, admin, MembershipRole.OWNER)
    staff = make_membership(restaurant, make_user(), MembershipRole.STAFF)
    api_client.force_login(admin)
    added = api_client.post(reverse("restaurant-members", kwargs={"slug": restaurant.slug}), {"email": "x@example.com", "password": STRONG, "role": "OWNER"}, format="json")
    assert added.status_code == 409 and added.json()["error"]["code"] == "single_owner"
    promoted = api_client.patch(reverse("restaurant-member", kwargs={"slug": restaurant.slug, "pk": staff.pk}), {"role": "OWNER"}, format="json")
    assert promoted.status_code == 409 and promoted.json()["error"]["code"] == "single_owner"


def test_self_service_users_get_exactly_one_restaurant(settings, make_user, make_restaurant, make_membership):
    settings.SELF_SERVICE = True
    settings.MAX_RESTAURANTS_PER_USER = 1
    user = make_user()
    assert can_create_restaurant(user) is True
    make_membership(make_restaurant(), user, MembershipRole.OWNER)
    assert can_create_restaurant(user) is False


def test_platform_audit_records_the_owner_actions(owner_client, plans):
    created = create(owner_client).json()["customer"]
    owner_client.post(f"{P}{created['id']}/reset-admin-password/")
    owner_client.post(f"{P}{created['id']}/extend/", {"days": 1}, format="json")
    actions = set(PlatformAuditEvent.objects.values_list("action", flat=True))
    assert {"customer.created", "customer.admin_password_reset", "customer.access_extended"} <= actions
    assert not any("chef@example.com" in e.summary for e in PlatformAuditEvent.objects.all())
