"""Reviews need a customer account, and each customer can review a restaurant once. Needs PostgreSQL like the rest of the suite."""
import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.orders.models import Order, OrderStatus
from apps.reviews.models import Review

pytestmark = pytest.mark.django_db
PASSWORD = "Tr1cky-Passphrase-9"


def sign_up(client, email="ada@example.com"):
    body = {"email": email, "password": PASSWORD, "first_name": "Ada", "last_name": "Obi", "phone": "+2348012345678"}
    assert client.post(reverse("customer-register"), body, format="json").status_code == 201


def order_as(client, shop, name="Ada"):
    """An order placed by THIS client (signed in or not)."""
    body = {"customer_name": name, "customer_phone": "+442079460958", "fulfilment_type": "PICKUP", "pickup_at": (timezone.now() + timedelta(hours=2)).isoformat(),
            "items": [{"menu_item_id": shop.rice.pk, "quantity": 1}]}
    response = client.post(reverse("public-order-create", kwargs={"slug": shop.restaurant.slug}), body, format="json", HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex)
    assert response.status_code == 201, response.content
    token = response.json()["token"]
    Order.objects.filter(reference=response.json()["reference"]).update(status=OrderStatus.COMPLETED)
    return token


def view(client, token):
    return client.get(reverse("public-order", kwargs={"token": token})).json()


def review(client, token, rating=5, comment="Lovely"):
    return client.post(reverse("public-order-review", kwargs={"token": token}), {"rating": rating, "comment": comment}, format="json")


# ---------------------------------------------------------------- signing in is required
def test_a_visitor_who_is_not_signed_in_cannot_review_and_is_told_to_sign_in(shop):
    guest = APIClient()
    token = order_as(guest, shop)
    body = view(guest, token)
    assert (body["can_review"], body["review_status"]) == (False, "sign_in")
    assert review(guest, token).status_code in (401, 403)
    assert Review.objects.count() == 0


def test_a_signed_in_customer_can_review_their_completed_order(shop):
    client = APIClient()
    sign_up(client)
    token = order_as(client, shop)
    assert view(client, token)["review_status"] == "can_review"
    response = review(client, token, 4, "Great jollof")
    assert response.status_code == 201
    saved = Review.objects.get()
    assert (saved.rating, saved.customer.user.email, saved.restaurant) == (4, "ada@example.com", shop.restaurant)
    body = response.json()
    assert body["review"]["rating"] == 4 and body["review_status"] == "" and body["can_review"] is False


def test_an_order_that_is_not_completed_cannot_be_reviewed(shop):
    client = APIClient()
    sign_up(client)
    token = order_as(client, shop)
    Order.objects.update(status=OrderStatus.SERVING)
    assert view(client, token)["review_status"] == ""
    assert review(client, token).status_code == 409


# ---------------------------------------------------------------- once per restaurant
def test_a_second_order_from_the_same_restaurant_does_not_offer_another_review(shop):
    client = APIClient()
    sign_up(client)
    first, second = order_as(client, shop), order_as(client, shop)
    assert review(client, first).status_code == 201
    later = view(client, second)
    assert (later["can_review"], later["review_status"]) == (False, "")  # nothing to show on the page
    blocked = review(client, second)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "already_reviewed_restaurant"
    assert Review.objects.count() == 1


def test_the_same_order_cannot_be_reviewed_twice(shop):
    client = APIClient()
    sign_up(client)
    token = order_as(client, shop)
    assert review(client, token).status_code == 201
    assert review(client, token).json()["error"]["code"] == "already_reviewed"


def test_a_customer_can_review_a_different_restaurant(shop, make_restaurant, make_category, make_item):
    client = APIClient()
    sign_up(client)
    assert review(client, order_as(client, shop)).status_code == 201
    other = make_restaurant(accepting_orders=True)
    other_shop = type("S", (), {"restaurant": other, "rice": make_item(make_category(other), price="3.00")})
    assert review(client, order_as(client, other_shop)).status_code == 201
    assert Review.objects.count() == 2


def test_the_database_itself_refuses_a_second_review_by_the_same_customer(shop):
    client = APIClient()
    sign_up(client)
    first, second = order_as(client, shop), order_as(client, shop)
    assert review(client, first).status_code == 201
    reviewed = Review.objects.get()
    other_order = Order.objects.exclude(pk=reviewed.order_id).get()
    with pytest.raises(IntegrityError), transaction.atomic():
        Review.objects.create(restaurant=shop.restaurant, order=other_order, customer=reviewed.customer, rating=3, display_name="Ada O.")


# ---------------------------------------------------------------- whose order is it
def test_reviewing_a_guest_order_while_signed_in_adds_it_to_the_account(shop):
    guest = APIClient()
    token = order_as(guest, shop)
    member = APIClient()
    sign_up(member)
    assert view(member, token)["review_status"] == "can_review"
    assert review(member, token).status_code == 201
    order = Order.objects.get()
    assert order.customer.user.email == "ada@example.com"


def test_a_customer_cannot_review_another_customers_order(shop):
    owner, other = APIClient(), APIClient()
    sign_up(owner)
    token = order_as(owner, shop)
    sign_up(other, "tunde@example.com")
    assert view(other, token)["review_status"] == ""
    response = review(other, token)
    assert response.status_code == 409 and response.json()["error"]["code"] == "not_your_order"


def test_a_restaurant_user_is_not_a_customer_and_cannot_review(shop, staff_login):
    guest = APIClient()
    token = order_as(guest, shop)
    from apps.restaurants.models import MembershipRole

    staff = APIClient()
    staff.force_login(staff_login(shop.restaurant, MembershipRole.OWNER))
    assert view(staff, token)["review_status"] == "sign_in"
    assert review(staff, token).status_code in (401, 403)


# ---------------------------------------------------------------- "My orders" follows the same rules
def test_my_orders_stops_offering_a_review_once_the_restaurant_has_been_reviewed(shop):
    client = APIClient()
    sign_up(client)
    first, second = order_as(client, shop), order_as(client, shop)
    before = client.get(reverse("customer-orders")).json()["results"]
    assert [row["can_review"] for row in before] == [True, True]
    assert review(client, first).status_code == 201
    rows = {row["public_id"]: row for row in client.get(reverse("customer-orders")).json()["results"]}
    assert sorted((row["reviewed"], row["can_review"]) for row in rows.values()) == [(False, False), (True, False)]
