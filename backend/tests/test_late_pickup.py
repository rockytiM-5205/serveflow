"""The late pickup policy: set by the restaurant, accepted by the customer first, started only by the restaurant's ready mark."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.orders import lateness
from apps.orders.models import ActorType, Order, OrderStatus
from apps.orders.workflow import change_status
from apps.restaurants.models import MembershipRole

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 11, 9, 12, 0, tzinfo=dt_timezone.utc)
POLICY = {"grace_minutes": 15, "fee_amount": "100.00", "interval_minutes": 15, "max_fee": "300.00"}


def code(response):
    return response.json()["error"]["code"]


@pytest.fixture
def policy_on(shop):
    r = shop.restaurant
    r.late_fee_enabled, r.late_grace_minutes = True, 15
    r.late_fee_amount, r.late_fee_interval_minutes, r.late_fee_max = Decimal("100.00"), 15, Decimal("300.00")
    r.save()
    return r


def fake(ready=None, pickup=None, policy=POLICY, fulfilment="PICKUP"):
    return SimpleNamespace(late_policy=policy, ready_at=ready, pickup_at=pickup, fulfilment_type=fulfilment)


# ---------------------------------------------------------------- the maths
def test_no_ready_mark_means_no_clock_and_no_fee():
    order = fake(ready=None, pickup=T0)
    assert lateness.free_until(order) is None
    assert lateness.compute_late_fee(order, T0 + timedelta(hours=5)) == (Decimal("0.00"), 0)  # the restaurant never said it was ready


def test_the_grace_period_is_free_and_the_boundary_is_free():
    order = fake(ready=T0, pickup=T0)
    assert lateness.free_until(order) == T0 + timedelta(minutes=15)
    assert lateness.compute_late_fee(order, T0 + timedelta(minutes=15)) == (Decimal("0.00"), 0)
    assert lateness.compute_late_fee(order, T0 + timedelta(minutes=16)) == (Decimal("100.00"), 1)


def test_the_fee_grows_by_interval_and_stops_at_the_maximum():
    order = fake(ready=T0, pickup=T0)
    after = lambda minutes: lateness.compute_late_fee(order, T0 + timedelta(minutes=15 + minutes))  # noqa: E731
    assert after(15) == (Decimal("100.00"), 15) and after(16) == (Decimal("200.00"), 16)  # a part interval counts as a whole one
    assert after(45) == (Decimal("300.00"), 45) and after(600) == (Decimal("300.00"), 600)  # never more than the cap


def test_the_clock_starts_at_the_later_of_ready_and_the_chosen_pickup_time():
    early_ready = fake(ready=T0, pickup=T0 + timedelta(hours=1))  # ready early: the customer isn't late for arriving at their own time
    assert lateness.free_until(early_ready) == T0 + timedelta(hours=1, minutes=15)
    late_ready = fake(ready=T0 + timedelta(hours=1), pickup=T0)  # the restaurant was late: its delay isn't the customer's
    assert lateness.free_until(late_ready) == T0 + timedelta(hours=1, minutes=15)


def test_dine_in_and_orders_without_a_policy_never_pay_a_late_fee():
    assert lateness.free_until(fake(ready=T0, pickup=T0, fulfilment="DINE_IN")) is None
    assert lateness.free_until(fake(ready=T0, pickup=T0, policy=None)) is None


# ---------------------------------------------------------------- the restaurant sets the rules
def settings_url(shop):
    return reverse("restaurant-settings", kwargs={"slug": shop.restaurant.slug})


def test_a_manager_sets_the_policy_and_customers_can_see_it(api_client, shop, staff_login):
    staff_login(shop.restaurant, MembershipRole.MANAGER)
    body = {"late_fee_enabled": True, "late_grace_minutes": 20, "late_fee_amount": "150.00", "late_fee_interval_minutes": 10, "late_fee_max": "450.00"}
    assert api_client.patch(settings_url(shop), body, format="json").status_code == 200
    public = api_client.get(reverse("public-restaurant", kwargs={"slug": shop.restaurant.slug})).json()
    assert public["late_policy"] == {"grace_minutes": 20, "fee_amount": "150.00", "interval_minutes": 10, "max_fee": "450.00"}


def test_a_restaurant_with_no_policy_shows_none(api_client, shop):
    assert api_client.get(reverse("public-restaurant", kwargs={"slug": shop.restaurant.slug})).json()["late_policy"] is None


@pytest.mark.parametrize("body, field", [
    ({"late_fee_enabled": True}, "late_fee_amount"),                                                              # on, but no fee
    ({"late_fee_enabled": True, "late_fee_amount": "100", "late_fee_max": "50"}, "late_fee_max"),                  # cap below one fee
    ({"late_fee_enabled": True, "late_fee_amount": "100", "late_fee_max": "300", "late_fee_interval_minutes": 2}, "late_fee_interval_minutes"),
    ({"late_grace_minutes": 500}, "late_grace_minutes"),
    ({"late_fee_amount": "-5"}, "late_fee_amount"),
])
def test_the_policy_must_make_sense(api_client, shop, staff_login, body, field):
    staff_login(shop.restaurant, MembershipRole.MANAGER)
    response = api_client.patch(settings_url(shop), body, format="json")
    assert response.status_code == 400 and field in response.json()["error"]["details"]


def test_staff_cannot_change_the_policy(api_client, shop, staff_login):
    staff_login(shop.restaurant, MembershipRole.STAFF)
    assert api_client.patch(settings_url(shop), {"late_fee_enabled": False}, format="json").status_code == 403


# ---------------------------------------------------------------- the customer must accept it first
def test_a_pickup_order_cannot_be_placed_without_accepting_the_policy(place, shop, policy_on):
    response = place(shop.restaurant, [(shop.rice.pk, 1)])
    assert response.status_code == 400 and "accept_late_policy" in response.json()["error"]["details"]
    assert not Order.objects.exists()
    declined = place(shop.restaurant, [(shop.rice.pk, 1)], accept_late_policy=False)
    assert declined.status_code == 400


def test_accepting_copies_the_rules_onto_the_order_for_good(place, shop, policy_on):
    body = place(shop.restaurant, [(shop.rice.pk, 1)], accept_late_policy=True).json()
    order = Order.objects.get()
    assert order.late_policy == POLICY and order.late_policy_accepted_at is not None
    assert body["pickup_policy"]["fee_amount"] == "100.00" and body["pickup_policy"]["free_until"] is None  # no clock until it is ready
    policy_on.late_fee_amount, policy_on.late_fee_max = Decimal("999.00"), Decimal("999.00")
    policy_on.save()  # the restaurant changes its mind later
    assert Order.objects.get().late_policy == POLICY


def test_dine_in_and_restaurants_without_a_policy_need_no_acceptance(place, shop, policy_on):
    assert place(shop.restaurant, [(shop.rice.pk, 1)], fulfilment_type="DINE_IN", table_number="3").status_code == 201
    policy_on.late_fee_enabled = False
    policy_on.save()
    created = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460777")
    assert created.status_code == 201 and created.json()["pickup_policy"] is None


# ---------------------------------------------------------------- the fee is worked out once, at collection
def order_ready_and_collected(place, shop, monkeypatch, ready_after, collect_after, **extra):
    created = place(shop.restaurant, [(shop.rice.pk, 1)], accept_late_policy=True, **extra).json()
    order = Order.objects.get(reference=created["reference"])
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.SERVING, payment_status="PAID")
    base = order.pickup_at
    for step, when in (("READY_FOR_PICKUP", base + ready_after), ("COMPLETED", base + collect_after)):
        monkeypatch.setattr(timezone, "now", lambda when=when: when)
        order = change_status(order=Order.objects.get(pk=order.pk), to_status=step, actor_type=ActorType.STAFF, actor_user=None)
    return order, created["token"]


def test_collecting_late_creates_a_fee_that_is_due(place, shop, policy_on, monkeypatch):
    order, _ = order_ready_and_collected(place, shop, monkeypatch, timedelta(minutes=-10), timedelta(minutes=25))  # 10 minutes late
    assert (order.late_fee, order.late_fee_status) == (Decimal("100.00"), "DUE")
    assert AuditLog.objects.filter(action="order.late_fee_due").count() == 1
    assert order.total == Order.objects.get().total  # the amount paid up front is untouched


def test_collecting_within_the_grace_period_costs_nothing(place, shop, policy_on, monkeypatch):
    order, _ = order_ready_and_collected(place, shop, monkeypatch, timedelta(minutes=-10), timedelta(minutes=10))
    assert (order.late_fee, order.late_fee_status) == (Decimal("0.00"), "NONE")


def test_a_restaurant_that_marks_ready_late_cannot_charge_for_its_own_delay(place, shop, policy_on, monkeypatch):
    order, _ = order_ready_and_collected(place, shop, monkeypatch, timedelta(minutes=40), timedelta(minutes=45))  # ready 40 min after the slot
    assert order.late_fee_status == "NONE"


def test_skipping_the_ready_mark_means_no_late_fee(place, shop, policy_on, monkeypatch):
    created = place(shop.restaurant, [(shop.rice.pk, 1)], accept_late_policy=True).json()
    order = Order.objects.get(reference=created["reference"])
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.SERVING, payment_status="PAID")
    monkeypatch.setattr(timezone, "now", lambda: order.pickup_at + timedelta(hours=3))
    done = change_status(order=Order.objects.get(pk=order.pk), to_status=OrderStatus.COMPLETED, actor_type=ActorType.STAFF, actor_user=None)
    assert done.late_fee_status == "NONE"


def test_the_customer_sees_the_clock_and_the_fee(api_client, place, shop, policy_on, monkeypatch):
    order, token = order_ready_and_collected(place, shop, monkeypatch, timedelta(0), timedelta(minutes=50))  # 35 minutes late: 3 intervals, capped at 300
    body = api_client.get(reverse("public-order", kwargs={"token": token})).json()
    assert body["late_fee"] == {"amount": "300.00", "status": "DUE"}
    assert body["pickup_policy"]["free_until"] == (order.pickup_at + timedelta(minutes=15)).isoformat().replace("+00:00", "+00:00")


def test_the_database_refuses_a_late_fee_without_an_accepted_policy(place, shop):
    from django.db import IntegrityError, transaction

    place(shop.restaurant, [(shop.rice.pk, 1)])
    order = Order.objects.get()
    for fields in ({"late_fee": Decimal("50.00"), "late_fee_status": "DUE"}, {"late_fee_status": "DUE"}):
        with pytest.raises(IntegrityError), transaction.atomic():
            Order.objects.filter(pk=order.pk).update(**fields)


# ---------------------------------------------------------------- staff settle it, and it is audited
def staff_url(name, shop, order):
    return reverse(name, kwargs={"slug": shop.restaurant.slug, "public_id": order.public_id})


def due_order(place, shop, policy_on, monkeypatch):
    order, _ = order_ready_and_collected(place, shop, monkeypatch, timedelta(0), timedelta(minutes=40))
    monkeypatch.undo()
    return order


def test_staff_mark_a_late_fee_collected(api_client, place, shop, policy_on, monkeypatch, staff_login):
    order = due_order(place, shop, policy_on, monkeypatch)
    staff_login(shop.restaurant, MembershipRole.STAFF)
    response = api_client.post(staff_url("staff-order-late-fee", shop, order), {"action": "paid"}, format="json")
    assert response.status_code == 200 and response.json()["late_fee_status"] == "PAID"
    assert AuditLog.objects.filter(action="order.late_fee_paid").count() == 1
    again = api_client.post(staff_url("staff-order-late-fee", shop, order), {"action": "paid"}, format="json")
    assert again.status_code == 409 and code(again) == "no_late_fee_due"


def test_only_a_manager_with_a_reason_can_waive_a_late_fee(api_client, place, shop, policy_on, monkeypatch, staff_login):
    order = due_order(place, shop, policy_on, monkeypatch)
    url = staff_url("staff-order-late-fee", shop, order)
    staff_login(shop.restaurant, MembershipRole.STAFF)
    assert api_client.post(url, {"action": "waive", "reason": "Regular customer"}, format="json").status_code == 403
    staff_login(shop.restaurant, MembershipRole.MANAGER)
    assert api_client.post(url, {"action": "waive"}, format="json").status_code == 400
    waived = api_client.post(url, {"action": "waive", "reason": "Traffic, first time"}, format="json")
    assert waived.status_code == 200 and waived.json()["late_fee_status"] == "WAIVED"
    event = AuditLog.objects.get(action="order.late_fee_waived")
    assert event.metadata["reason"] == "Traffic, first time" and event.actor is not None


def test_an_order_with_no_late_fee_cannot_be_settled(api_client, place, shop, staff_login):
    place(shop.restaurant, [(shop.rice.pk, 1)])
    staff_login(shop.restaurant, MembershipRole.MANAGER)
    response = api_client.post(staff_url("staff-order-late-fee", shop, Order.objects.get()), {"action": "paid"}, format="json")
    assert response.status_code == 409 and code(response) == "no_late_fee_due"


def test_another_restaurants_staff_cannot_settle_a_late_fee(api_client, place, shop, policy_on, monkeypatch, make_restaurant, staff_login):
    order = due_order(place, shop, policy_on, monkeypatch)
    other = make_restaurant()
    staff_login(other, MembershipRole.OWNER)
    url = reverse("staff-order-late-fee", kwargs={"slug": other.slug, "public_id": order.public_id})
    assert api_client.post(url, {"action": "paid"}, format="json").status_code == 404
    assert Order.objects.get(pk=order.pk).late_fee_status == "DUE"
