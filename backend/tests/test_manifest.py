"""A restaurant's own installable-app manifest. Needs PostgreSQL like the rest of the suite."""
import pytest
from django.urls import reverse

from apps.restaurants.models import Restaurant

pytestmark = pytest.mark.django_db


def manifest_url(restaurant):
    return reverse("restaurant-manifest", kwargs={"slug": restaurant.slug})


def test_a_restaurant_gets_its_own_manifest(api_client, shop):
    response = api_client.get(manifest_url(shop.restaurant))
    assert response.status_code == 200 and response["Content-Type"].startswith("application/manifest+json")
    body = response.json()
    assert body["name"] == shop.restaurant.name and body["display"] == "standalone"
    assert body["start_url"] == f"/customer/index.html?r={shop.restaurant.slug}" == body["id"]
    assert body["scope"] == "/customer/" and body["start_url"].startswith(body["scope"])
    assert {i["sizes"] for i in body["icons"]} >= {"192x192", "512x512"}
    assert "max-age" in response["Cache-Control"]


def test_the_short_name_fits_under_an_icon(api_client, make_restaurant):
    restaurant = make_restaurant(name="The Very Long Restaurant Name Ltd")
    assert len(api_client.get(manifest_url(restaurant)).json()["short_name"]) <= 12


def test_the_restaurants_logo_comes_first_with_the_standard_icons_behind_it(api_client, shop):
    Restaurant.objects.filter(pk=shop.restaurant.pk).update(logo=f"restaurants/{shop.restaurant.pk}/logo/a.webp")
    icons = api_client.get(manifest_url(shop.restaurant)).json()["icons"]
    assert icons[0]["src"].endswith("/logo/a.webp") and icons[0]["src"].startswith("/") and len(icons) >= 4


def test_without_a_logo_only_the_standard_icons_are_listed(api_client, shop):
    assert all(i["src"].startswith("/shared/assets/icons/") for i in api_client.get(manifest_url(shop.restaurant)).json()["icons"])


def test_unknown_and_suspended_restaurants_have_no_manifest(api_client, shop, make_restaurant):
    assert api_client.get(reverse("restaurant-manifest", kwargs={"slug": "no-such-place"})).status_code == 404
    Restaurant.objects.filter(pk=shop.restaurant.pk).update(is_active=False)
    assert api_client.get(manifest_url(shop.restaurant)).status_code == 404
