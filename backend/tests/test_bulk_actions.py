"""Busy-hours tools: move many orders at once, pay-and-start in one tap, and accepting new orders automatically. Needs PostgreSQL."""
import uuid

import pytest
from django.urls import reverse

from apps.orders.models import Order, OrderStatus, OrderStatusEvent, PaymentStatus
from apps.restaurants.models import MembershipRole, Restaurant
from apps.orders.workflow import steps_to

pytestmark = pytest.mark.django_db
S = OrderStatus


def move(client, shop, orders, to_status):
    return client.post(
        reverse("staff-orders-transitions", kwargs={"slug": shop.restaurant.slug}),
        {"orders": [str(o.public_id) for o in orders], "to_status": to_status}, format="json",
    )


def pay_and_start(client, shop, orders, **extra):
    return client.post(
        reverse("staff-orders-confirm-payments", kwargs={"slug": shop.restaurant.slug}),
        {"orders": [str(o.public_id) for o in orders], **extra}, format="json", HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex,
    )


def paid(order_in, status="PENDING"):
    order = order_in(status)
    Order.objects.filter(pk=order.pk).update(payment_status=PaymentStatus.PAID)
    return order


# ---------------------------------------------------------------- the path an order takes
def test_the_steps_between_two_statuses():
    assert steps_to(S.PENDING, S.SERVING) == [S.CONFIRMED, S.SERVING]
    assert steps_to(S.CONFIRMED, S.READY_FOR_PICKUP) == [S.SERVING, S.READY_FOR_PICKUP]
    assert steps_to(S.SERVING, S.COMPLETED) == [S.COMPLETED]  # "ready" is optional
    assert steps_to(S.PENDING, S.COMPLETED) == [S.CONFIRMED, S.SERVING, S.COMPLETED]
    assert steps_to(S.SERVING, S.CONFIRMED) == [] and steps_to(S.REJECTED, S.SERVING) is None


# ---------------------------------------------------------------- bulk moves
def test_many_paid_orders_go_straight_to_preparing(api_client, shop, order_in, staff_login):
    orders = [paid(order_in) for _ in range(3)]
    user = staff_login(shop.restaurant, MembershipRole.STAFF)
    body = move(api_client, shop, orders, "SERVING").json()
    assert sorted(body["moved"]) == sorted(str(o.public_id) for o in orders) and body["skipped"] == []
    assert set(Order.objects.values_list("status", flat=True)) == {"SERVING"}
    steps = OrderStatusEvent.objects.filter(order=orders[0]).order_by("id")
    assert [(e.from_status, e.to_status, e.actor_user_id) for e in steps] == [
        (None, "PENDING", None), ("PENDING", "CONFIRMED", user.pk), ("CONFIRMED", "SERVING", user.pk)]


def test_an_unpaid_order_is_skipped_and_stays_where_it_was(api_client, shop, order_in, staff_login):
    ok, unpaid = paid(order_in), order_in()
    staff_login(shop.restaurant, MembershipRole.STAFF)
    body = move(api_client, shop, [ok, unpaid], "SERVING").json()
    assert body["moved"] == [str(ok.public_id)]
    assert body["skipped"] == [{"public_id": str(unpaid.public_id), "reference": unpaid.reference, "reason": "payment_required"}]
    unpaid.refresh_from_db()
    assert unpaid.status == S.PENDING  # the accept step was rolled back with it


def test_orders_already_there_or_closed_are_skipped(api_client, shop, order_in, staff_login):
    serving, rejected = paid(order_in, "SERVING"), order_in("REJECTED")
    staff_login(shop.restaurant, MembershipRole.STAFF)
    body = move(api_client, shop, [serving, rejected], "SERVING").json()
    assert body["moved"] == [] and {s["reason"] for s in body["skipped"]} == {"already_there", "invalid_transition"}


def test_serving_orders_can_be_marked_ready_then_completed_together(api_client, shop, order_in, staff_login):
    orders = [paid(order_in, "SERVING") for _ in range(2)]
    staff_login(shop.restaurant, MembershipRole.STAFF)
    assert len(move(api_client, shop, orders, "READY_FOR_PICKUP").json()["moved"]) == 2
    assert set(Order.objects.values_list("ready_at__isnull", flat=True)) == {False}
    assert len(move(api_client, shop, orders, "COMPLETED").json()["moved"]) == 2
    assert set(Order.objects.values_list("status", flat=True)) == {"COMPLETED"}


def test_only_the_normal_forward_statuses_are_accepted(api_client, shop, order_in, staff_login):
    order = order_in()
    staff_login(shop.restaurant, MembershipRole.STAFF)
    for bad in ("CANCELLED", "REJECTED", "PENDING", "nonsense"):
        assert move(api_client, shop, [order], bad).status_code == 400
    assert api_client.post(reverse("staff-orders-transitions", kwargs={"slug": shop.restaurant.slug}), {"orders": [], "to_status": "CONFIRMED"}, format="json").status_code == 400


def test_another_restaurants_orders_are_never_moved(api_client, shop, order_in, staff_login, make_restaurant, make_category, make_item, place):
    other = make_restaurant(accepting_orders=True)
    place(other, [(make_item(make_category(other)).pk, 1)])
    foreign = Order.objects.get(restaurant=other)
    staff_login(shop.restaurant, MembershipRole.STAFF)
    assert move(api_client, shop, [foreign], "CONFIRMED").json()["skipped"][0]["reason"] == "not_found"
    foreign.refresh_from_db()
    assert foreign.status == S.PENDING


# ---------------------------------------------------------------- confirm payment and start preparing
def test_confirming_payments_can_also_start_preparing(api_client, shop, order_in, staff_login):
    orders = [order_in() for _ in range(3)]
    staff_login(shop.restaurant, MembershipRole.STAFF)
    body = pay_and_start(api_client, shop, orders, start_preparing=True).json()
    assert len(body["confirmed"]) == 3 and body["skipped"] == []
    assert set(Order.objects.values_list("status", "payment_status")) == {("SERVING", "PAID")}


def test_confirming_payments_alone_does_not_start_anything(api_client, shop, order_in, staff_login):
    orders = [order_in() for _ in range(2)]
    staff_login(shop.restaurant, MembershipRole.STAFF)
    pay_and_start(api_client, shop, orders)
    assert set(Order.objects.values_list("status", flat=True)) == {"PENDING"}


# ---------------------------------------------------------------- accept automatically
def test_a_new_order_is_accepted_automatically_when_the_restaurant_asks(shop, order_in):
    Restaurant.objects.filter(pk=shop.restaurant.pk).update(auto_accept_orders=True)
    order = order_in()
    assert order.status == S.CONFIRMED and order.payment_status == PaymentStatus.UNPAID  # still has to be paid before preparing
    first, second = OrderStatusEvent.objects.filter(order=order).order_by("id")
    assert (second.from_status, second.to_status, second.actor_type, second.reason) == ("PENDING", "CONFIRMED", "SYSTEM", "Accepted automatically")


def test_orders_wait_for_staff_by_default(shop, order_in):
    assert order_in().status == S.PENDING


def test_a_manager_can_switch_automatic_accepting_on(api_client, shop, staff_login):
    staff_login(shop.restaurant, MembershipRole.OWNER)
    url = reverse("restaurant-settings", kwargs={"slug": shop.restaurant.slug})
    assert api_client.patch(url, {"auto_accept_orders": True}, format="json").json()["auto_accept_orders"] is True
    staff_login(shop.restaurant, MembershipRole.STAFF)
    assert api_client.patch(url, {"auto_accept_orders": False}, format="json").status_code == 403  # staff can only pause orders
