"""Each restaurant's own order prefix and the references built from it. Needs PostgreSQL like the rest of the suite."""
import re

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.orders.models import Order, generate_reference
from apps.restaurants.models import MembershipRole, Restaurant
from apps.restaurants.prefixes import suggest_prefix, unique_prefix

pytestmark = pytest.mark.django_db


def settings_url(restaurant):
    return reverse("restaurant-settings", kwargs={"slug": restaurant.slug})


# ---------------------------------------------------------------- the prefix
def test_a_prefix_is_suggested_from_the_name():
    assert suggest_prefix("Pramos Kitchen") == "PKR"
    assert suggest_prefix("Mama Put") == "MPA"
    assert re.fullmatch(r"[A-Z]{3}", suggest_prefix("???"))


def test_a_taken_prefix_is_never_reused():
    chosen = unique_prefix("Pramos Kitchen", lambda p: p == "PKR")
    assert chosen != "PKR" and re.fullmatch(r"[A-Z][A-Z0-9]{2,4}", chosen)


def test_every_new_restaurant_gets_a_distinct_prefix(make_restaurant):
    first, second = make_restaurant(name="Pramos Kitchen"), make_restaurant(name="Pramos Kitchen")
    assert first.order_prefix and second.order_prefix and first.order_prefix != second.order_prefix


def test_a_chosen_prefix_is_kept(make_restaurant):
    assert make_restaurant(name="Pramos", order_prefix="PRM").order_prefix == "PRM"


def test_the_database_refuses_a_malformed_prefix(make_restaurant):
    from django.db import IntegrityError, transaction

    restaurant = make_restaurant()
    with pytest.raises(IntegrityError), transaction.atomic():
        Restaurant.objects.filter(pk=restaurant.pk).update(order_prefix="1ab")


# ---------------------------------------------------------------- settings
def test_the_prefix_can_change_until_the_restaurant_has_orders(api_client, shop, staff_login, place):
    staff_login(shop.restaurant, MembershipRole.OWNER)
    assert api_client.get(settings_url(shop.restaurant)).json()["order_prefix_locked"] is False
    response = api_client.patch(settings_url(shop.restaurant), {"order_prefix": "pra"}, format="json")
    assert response.status_code == 200 and response.json()["order_prefix"] == "PRA"
    assert api_client.patch(settings_url(shop.restaurant), {"order_prefix": "1x"}, format="json").status_code == 400

    assert place(shop.restaurant, [(shop.rice.pk, 1)]).status_code == 201
    locked = api_client.patch(settings_url(shop.restaurant), {"order_prefix": "NEW"}, format="json")
    assert locked.status_code == 400 and "order_prefix" in locked.json()["error"]["details"]
    assert api_client.get(settings_url(shop.restaurant)).json()["order_prefix_locked"] is True


def test_two_restaurants_cannot_share_a_prefix(api_client, shop, staff_login, make_restaurant):
    other = make_restaurant(order_prefix="ZZZ")
    staff_login(shop.restaurant, MembershipRole.OWNER)
    assert api_client.patch(settings_url(shop.restaurant), {"order_prefix": other.order_prefix}, format="json").status_code == 400


# ---------------------------------------------------------------- the reference
def test_a_new_order_carries_its_restaurants_prefix(place, shop):
    body = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    assert re.fullmatch(rf"{shop.restaurant.order_prefix}-[2-9A-HJKMNP-Z]{{5}}", body["reference"])
    assert Order.objects.get().reference == body["reference"]


def test_references_from_two_restaurants_never_collide(place, shop, make_restaurant, make_category, make_item):
    other = make_restaurant(accepting_orders=True)
    assert shop.restaurant.order_prefix != other.order_prefix
    assert generate_reference(shop.restaurant).split("-")[0] != generate_reference(other).split("-")[0]


def test_an_older_restaurant_gets_its_prefix_when_it_takes_an_order(place, shop):
    Restaurant.objects.filter(pk=shop.restaurant.pk).update(order_prefix=None)
    body = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    shop.restaurant.refresh_from_db()
    assert shop.restaurant.order_prefix and body["reference"].startswith(shop.restaurant.order_prefix + "-")


def test_an_older_order_keeps_its_old_reference(place, shop):
    body = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    Order.objects.filter(reference=body["reference"]).update(reference="7K#M4@2P")
    assert Order.objects.get().reference == "7K#M4@2P"


def test_staff_can_find_an_order_by_just_the_end_of_its_reference(api_client, shop, order_in, staff_login):
    order = order_in()
    staff_login(shop.restaurant, MembershipRole.STAFF)
    list_url = reverse("staff-orders", kwargs={"slug": shop.restaurant.slug})
    tail = order.reference.split("-")[1]
    assert [o["reference"] for o in api_client.get(list_url, {"search": tail.lower()}).json()["results"]] == [order.reference]
    assert api_client.get(list_url, {"search": "ZZZZZ"}).json()["results"] == []


def test_the_backfill_command_gives_restaurants_a_prefix(shop):
    Restaurant.objects.filter(pk=shop.restaurant.pk).update(order_prefix=None)
    call_command("backfill_order_prefixes")
    shop.restaurant.refresh_from_db()
    assert re.fullmatch(r"[A-Z][A-Z0-9]{2,4}", shop.restaurant.order_prefix)
