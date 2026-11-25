"""Confirming many payments at once. Needs PostgreSQL like the rest of the suite."""
import uuid

import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.orders.models import Order, OrderStatus, Payment, PaymentStatus
from apps.restaurants.models import MembershipRole

pytestmark = pytest.mark.django_db


def bulk(client, shop, ids, key=None, **extra):
    return client.post(
        reverse("staff-orders-confirm-payments", kwargs={"slug": shop.restaurant.slug}),
        {"orders": [str(i) for i in ids], **extra}, format="json", HTTP_IDEMPOTENCY_KEY=key or uuid.uuid4().hex,
    )


def three_orders(order_in):
    return [order_in() for _ in range(3)]


def test_one_request_confirms_many_payments(api_client, shop, order_in, staff_login):
    orders = three_orders(order_in)
    user = staff_login(shop.restaurant, MembershipRole.STAFF)
    response = bulk(api_client, shop, [o.public_id for o in orders])
    assert response.status_code == 200
    assert sorted(response.json()["confirmed"]) == sorted(str(o.public_id) for o in orders) and response.json()["skipped"] == []
    assert set(Order.objects.values_list("payment_status", flat=True)) == {PaymentStatus.PAID}
    payments = Payment.objects.all()
    assert payments.count() == 3 and all(p.method == "TRANSFER" and p.recorded_by == user for p in payments)
    assert {p.reference for p in payments} == {o.reference for o in orders}  # the order's own reference is the bank reference
    assert AuditLog.objects.filter(action="payment.recorded").count() == 3
    assert AuditLog.objects.get(action="payment.bulk_confirmed").metadata == {"count": 3, "method": "TRANSFER"}


def test_an_order_that_cannot_be_paid_is_skipped_and_the_rest_still_go_through(api_client, shop, order_in, staff_login):
    good, already_paid, rejected = three_orders(order_in)
    Order.objects.filter(pk=already_paid.pk).update(payment_status=PaymentStatus.PAID)
    Order.objects.filter(pk=rejected.pk).update(status=OrderStatus.REJECTED)
    staff_login(shop.restaurant, MembershipRole.STAFF)
    body = bulk(api_client, shop, [good.public_id, already_paid.public_id, rejected.public_id]).json()
    assert body["confirmed"] == [str(good.public_id)]
    assert {(s["public_id"], s["reason"]) for s in body["skipped"]} == {
        (str(already_paid.public_id), "already_paid"), (str(rejected.public_id), "not_payable"),
    }
    assert Payment.objects.count() == 1


def test_another_restaurants_order_is_never_touched(api_client, shop, order_in, staff_login, make_restaurant, make_category, make_item, place):
    other = make_restaurant(accepting_orders=True)
    place(other, [(make_item(make_category(other)).pk, 1)])
    foreign = Order.objects.get(restaurant=other)
    staff_login(shop.restaurant, MembershipRole.STAFF)
    body = bulk(api_client, shop, [foreign.public_id]).json()
    assert body["confirmed"] == [] and body["skipped"][0]["reason"] == "not_found"
    foreign.refresh_from_db()
    assert foreign.payment_status == PaymentStatus.UNPAID


def test_the_same_key_gives_the_same_answer_and_pays_nothing_twice(api_client, shop, order_in, staff_login):
    orders = three_orders(order_in)
    staff_login(shop.restaurant, MembershipRole.STAFF)
    ids, key = [o.public_id for o in orders], "k" * 20
    first = bulk(api_client, shop, ids, key=key)
    again = bulk(api_client, shop, ids, key=key)
    assert again.status_code == 200 and again.json() == first.json() and again.headers["Idempotent-Replay"] == "true"
    assert Payment.objects.count() == 3
    assert bulk(api_client, shop, ids[:1], key=key).status_code == 409  # same key, different request


def test_the_request_is_checked(api_client, shop, order_in, staff_login):
    staff_login(shop.restaurant, MembershipRole.STAFF)
    url = reverse("staff-orders-confirm-payments", kwargs={"slug": shop.restaurant.slug})
    assert api_client.post(url, {"orders": []}, format="json", HTTP_IDEMPOTENCY_KEY="k" * 20).status_code == 400
    too_many = [str(uuid.uuid4()) for _ in range(51)]
    assert api_client.post(url, {"orders": too_many}, format="json", HTTP_IDEMPOTENCY_KEY="k" * 20).status_code == 400
    assert api_client.post(url, {"orders": too_many[:1]}, format="json").status_code == 400  # no Idempotency-Key


def test_only_signed_in_staff_of_that_restaurant_can_confirm(api_client, shop, order_in, make_restaurant, staff_login):
    order = order_in()
    assert bulk(api_client, shop, [order.public_id]).status_code in (401, 403)
    staff_login(make_restaurant(), MembershipRole.STAFF)
    assert bulk(api_client, shop, [order.public_id]).status_code in (403, 404)
    assert Payment.objects.count() == 0
