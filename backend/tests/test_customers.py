"""Customer accounts: separate from restaurant users, optional (guests still order), with order history and linking."""
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.customers.models import CustomerProfile
from apps.orders.models import Order, OrderStatus
from apps.restaurants.models import MembershipRole
from apps.restaurants.services import can_create_restaurant

pytestmark = pytest.mark.django_db

PASSWORD = "Tr1cky-Passphrase-9"
User = get_user_model()


def register(client, email="ada@example.com", **extra):
    body = {"email": email, "password": PASSWORD, "first_name": "Ada", "last_name": "Obi", "phone": "+2348012345678", **extra}
    return client.post(reverse("customer-register"), body, format="json")


def error_code(response):
    return response.json()["error"]["code"]


# ---------------------------------------------------------------- registering and signing in
def test_registering_creates_a_customer_and_signs_them_in(api_client):
    response = register(api_client)
    assert response.status_code == 201
    assert response.json() == {"email": "ada@example.com", "first_name": "Ada", "last_name": "Obi", "phone": "+2348012345678"}
    user = User.objects.get(email="ada@example.com")
    assert CustomerProfile.objects.get(user=user).phone == "+2348012345678" and user.check_password(PASSWORD)
    assert api_client.get(reverse("customer-me")).json()["email"] == "ada@example.com"  # already signed in


@pytest.mark.parametrize("override, field", [
    ({"password": "short"}, "password"), ({"password": "password"}, "password"), ({"email": "nope"}, "email"),
    ({"first_name": ""}, "first_name"), ({"phone": "abc"}, "phone"),
])
def test_registration_is_validated(api_client, override, field):
    response = register(api_client, **override)
    assert response.status_code == 400 and field in response.json()["error"]["details"] and not CustomerProfile.objects.exists()


def test_an_email_can_only_be_used_once_whoever_has_it(api_client, make_user):
    make_user(email="owner@example.com")  # a restaurant user
    assert register(api_client, "owner@example.com").status_code == 400
    assert register(api_client, "ada@example.com").status_code == 201
    other = APIClient()
    duplicate = register(other, "ADA@example.com")
    assert duplicate.status_code == 400 and "already exists" in duplicate.json()["error"]["details"]["email"][0]


def test_signing_in_and_out(api_client):
    register(APIClient())
    assert api_client.post(reverse("customer-login"), {"email": "Ada@Example.com", "password": PASSWORD}, format="json").status_code == 200
    assert api_client.get(reverse("customer-me")).status_code == 200
    assert api_client.post(reverse("customer-logout")).status_code == 204
    assert api_client.get(reverse("customer-me")).status_code in (401, 403)


def test_a_wrong_password_an_unknown_email_and_a_restaurant_user_all_get_the_same_answer(api_client, make_user):
    register(APIClient())
    staff = make_user(email="staff@example.com", password=PASSWORD)
    attempts = [("ada@example.com", "wrong-password-1"), ("ghost@example.com", PASSWORD), (staff.email, PASSWORD)]
    answers = {(r.status_code, r.json()["error"]["message"]) for r in (
        api_client.post(reverse("customer-login"), {"email": e, "password": p}, format="json") for e, p in attempts)}
    assert answers == {(401, "Invalid email or password.")}  # a restaurant account can't be told apart from a missing one


def test_login_and_registration_enforce_csrf_like_the_rest_of_the_sign_in(db):
    strict = APIClient(enforce_csrf_checks=True)
    assert strict.post(reverse("customer-login"), {"email": "a@example.com", "password": PASSWORD}, format="json").status_code == 403
    assert register(strict).status_code == 403
    strict.get(reverse("auth-csrf"))
    token = strict.cookies["csrftoken"].value
    ok = strict.post(reverse("customer-register"), {"email": "a@example.com", "password": PASSWORD, "first_name": "Ada"}, format="json", HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 201


# ---------------------------------------------------------------- separate from restaurant users
def test_a_customer_account_has_no_restaurant_powers(api_client, shop):
    register(api_client)
    user = User.objects.get(email="ada@example.com")
    assert can_create_restaurant(user) is False
    assert not user.is_staff and not user.is_superuser
    assert api_client.get(reverse("restaurant-settings", kwargs={"slug": shop.restaurant.slug})).status_code == 403
    assert api_client.get(reverse("platform-overview")).status_code == 403
    assert api_client.get(reverse("staff-orders", kwargs={"slug": shop.restaurant.slug})).status_code == 403


def test_restaurant_users_cannot_use_the_customer_routes(api_client, shop, staff_login):
    staff_login(shop.restaurant, MembershipRole.OWNER)
    for name in ("customer-me", "customer-orders"):
        assert api_client.get(reverse(name)).status_code in (401, 403)


def test_the_customer_routes_need_a_signed_in_customer(api_client):
    for name in ("customer-me", "customer-orders", "customer-logout"):
        method = api_client.post if name == "customer-logout" else api_client.get
        assert method(reverse(name)).status_code in (401, 403)


# ---------------------------------------------------------------- profile and password
def test_a_customer_can_update_their_name_and_phone(api_client):
    register(api_client)
    response = api_client.patch(reverse("customer-me"), {"first_name": "Adaeze", "phone": "+2349098765432"}, format="json")
    assert response.status_code == 200 and response.json()["first_name"] == "Adaeze" and response.json()["phone"] == "+2349098765432"
    assert api_client.patch(reverse("customer-me"), {"phone": "nope"}, format="json").status_code == 400
    assert api_client.patch(reverse("customer-me"), {"email": "new@example.com"}, format="json").json()["email"] == "ada@example.com"  # email isn't editable here


def test_changing_the_password_needs_the_current_one_and_a_strong_new_one(api_client):
    register(api_client)
    url = reverse("customer-password")
    assert api_client.post(url, {"current_password": "wrong", "new_password": "An0ther-Passphrase-7"}, format="json").status_code == 400
    assert api_client.post(url, {"current_password": PASSWORD, "new_password": "12345678"}, format="json").status_code == 400
    assert api_client.post(url, {"current_password": PASSWORD, "new_password": "An0ther-Passphrase-7"}, format="json").status_code == 204
    assert api_client.get(reverse("customer-me")).status_code == 200  # this device stays signed in
    assert User.objects.get(email="ada@example.com").check_password("An0ther-Passphrase-7")


# ---------------------------------------------------------------- order history
def place_as(client, place, shop, phone="+442079460001"):
    """Place an order as THIS client (the `place` fixture always uses the shared one)."""
    body = {
        "customer_name": "Ada", "customer_phone": phone, "fulfilment_type": "PICKUP", "pickup_at": (timezone.now() + timedelta(hours=2)).isoformat(),
        "items": [{"menu_item_id": shop.rice.pk, "quantity": 2}],
    }
    response = client.post(reverse("public-order-create", kwargs={"slug": shop.restaurant.slug}), body, format="json", HTTP_IDEMPOTENCY_KEY=uuid.uuid4().hex)
    assert response.status_code == 201, response.content
    return response.json()


def test_an_order_placed_while_signed_in_lands_in_their_history(api_client, place, shop):
    register(api_client)
    created = place_as(api_client, place, shop)
    rows = api_client.get(reverse("customer-orders")).json()["results"]
    assert [r["reference"] for r in rows] == [created["reference"]]
    row = rows[0]
    assert (row["status"], row["items_count"], row["active"], row["can_review"]) == ("PENDING", 2, True, False)
    assert row["restaurant"] == {"slug": shop.restaurant.slug, "name": shop.restaurant.name} and row["item_names"]
    assert api_client.get(reverse("public-order", kwargs={"token": row["track_token"]})).json()["reference"] == created["reference"]


def test_a_guest_order_stays_a_guest_order(api_client, place, shop):
    place_as(api_client, place, shop)
    assert Order.objects.get().customer_id is None


def test_history_shows_only_your_own_orders_and_can_filter_active(api_client, place, shop):
    mine, theirs = APIClient(), APIClient()
    register(mine)
    register(theirs, "bola@example.com")
    first = place_as(mine, place, shop, "+442079460001")
    place_as(theirs, place, shop, "+442079460002")
    Order.objects.filter(reference=first["reference"]).update(status=OrderStatus.COMPLETED)
    second = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460003").json()
    assert [r["reference"] for r in mine.get(reverse("customer-orders")).json()["results"]] == [first["reference"]]
    assert theirs.get(reverse("customer-orders")).json()["results"][0]["reference"] != first["reference"]
    assert mine.get(reverse("customer-orders"), {"active": "1"}).json()["results"] == []
    completed = mine.get(reverse("customer-orders")).json()["results"][0]
    assert completed["active"] is False and completed["can_review"] is True
    assert second["reference"] not in str(mine.get(reverse("customer-orders")).json())


def test_one_customer_cannot_open_anothers_order(api_client, place, shop):
    mine, theirs = APIClient(), APIClient()
    register(mine)
    register(theirs, "bola@example.com")
    created = place_as(mine, place, shop)
    order = Order.objects.get(reference=created["reference"])
    assert mine.get(reverse("customer-order", kwargs={"public_id": order.public_id})).status_code == 200
    assert theirs.get(reverse("customer-order", kwargs={"public_id": order.public_id})).status_code == 404
    detail = mine.get(reverse("customer-order", kwargs={"public_id": order.public_id})).json()
    assert detail["reference"] == created["reference"] and detail["payment"]["reference"] == created["reference"] and "token" in detail


# ---------------------------------------------------------------- adding a guest order
def test_a_guest_order_can_be_added_with_its_private_link(api_client, place, shop):
    guest = place(shop.restaurant, [(shop.rice.pk, 1)]).json()  # placed with no account
    register(api_client)
    response = api_client.post(reverse("customer-order-claim"), {"token": guest["token"]}, format="json")
    assert response.status_code == 200 and response.json()["reference"] == guest["reference"]
    assert Order.objects.get().customer.user.email == "ada@example.com"
    assert api_client.post(reverse("customer-order-claim"), {"token": guest["token"]}, format="json").status_code == 200  # saying it twice is fine
    assert [r["reference"] for r in api_client.get(reverse("customer-orders")).json()["results"]] == [guest["reference"]]


def test_an_order_cannot_be_taken_from_another_account_or_claimed_without_its_link(api_client, place, shop):
    guest = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    first, second = APIClient(), APIClient()
    register(first)
    register(second, "bola@example.com")
    assert first.post(reverse("customer-order-claim"), {"token": guest["token"]}, format="json").status_code == 200
    taken = second.post(reverse("customer-order-claim"), {"token": guest["token"]}, format="json")
    assert taken.status_code == 409 and error_code(taken) == "already_linked"
    for bad in (guest["reference"], guest["token"][:-1] + ("0" if guest["token"][-1] != "0" else "1"), ""):
        assert second.post(reverse("customer-order-claim"), {"token": bad}, format="json").status_code in (400, 404)
    assert Order.objects.get().customer.user.email == "ada@example.com"


def test_claiming_needs_a_customer_account(api_client, place, shop):
    guest = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    assert api_client.post(reverse("customer-order-claim"), {"token": guest["token"]}, format="json").status_code in (401, 403)


def test_deleting_an_account_keeps_the_restaurants_orders(api_client, place, shop):
    register(api_client)
    place_as(api_client, place, shop)
    User.objects.get(email="ada@example.com").delete()
    order = Order.objects.get()
    assert order.customer_id is None  # the restaurant's record survives; it just no longer belongs to an account
