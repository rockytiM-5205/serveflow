"""What the order page needs to draw a plate from what was ordered: each item's photo, dish style and category. Needs PostgreSQL."""
import pytest
from django.urls import reverse

from apps.menu.models import DishKind, MenuItem
from apps.restaurants.models import MembershipRole

pytestmark = pytest.mark.django_db


def order_lines(client, place, shop, *items):
    response = place(shop.restaurant, [(item.pk, 1) for item in items])
    assert response.status_code == 201, response.content
    return client.get(reverse("public-order", kwargs={"token": response.json()["token"]})).json()["items"]


def test_an_order_line_carries_its_photo_dish_style_and_category(api_client, shop, place):
    MenuItem.objects.filter(pk=shop.rice.pk).update(image_url="https://img.example.com/rice.jpg", dish_kind=DishKind.RICE)
    (line,) = order_lines(api_client, place, shop, shop.rice)
    assert line["image_url"] == "https://img.example.com/rice.jpg"
    assert line["dish_kind"] == "rice"
    assert line["category"] == shop.category.name


def test_an_item_with_no_photo_or_style_says_so_and_leaves_the_choice_to_the_page(api_client, shop, place):
    (line,) = order_lines(api_client, place, shop, shop.beans)
    assert line["image_url"] is None and line["dish_kind"] == ""


def test_the_plate_data_is_loaded_without_a_query_per_item(api_client, shop, place, django_assert_max_num_queries):
    token = place(shop.restaurant, [(shop.rice.pk, 1), (shop.beans.pk, 2)]).json()["token"]
    with django_assert_max_num_queries(12):
        assert api_client.get(reverse("public-order", kwargs={"token": token})).status_code == 200


def test_a_manager_can_choose_the_dish_style_and_only_a_real_one(api_client, shop, staff_login):
    staff_login(shop.restaurant, MembershipRole.MANAGER)
    url = reverse("staff-menu-item", kwargs={"slug": shop.restaurant.slug, "pk": shop.rice.pk})
    assert api_client.patch(url, {"dish_kind": "soup"}, format="json").json()["dish_kind"] == "soup"
    assert api_client.patch(url, {"dish_kind": "spaceship"}, format="json").status_code == 400
    assert api_client.patch(url, {"dish_kind": ""}, format="json").json()["dish_kind"] == ""  # back to automatic
