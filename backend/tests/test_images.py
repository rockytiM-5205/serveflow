"""Picture uploads: restaurant logo and cover, and menu item photos. Needs Pillow and PostgreSQL like the rest of the suite."""
import io
import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.audit.models import AuditLog
from apps.restaurants.models import MembershipRole


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)  # every test writes to its own throwaway folder
    return tmp_path


def picture(size=(40, 30), fmt="PNG", color="#c0392b"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def upload(data, name="photo.png", content_type="image/png"):
    return {"file": SimpleUploadedFile(name, data, content_type=content_type)}


@pytest.fixture
def setup(make_restaurant, make_category, make_item, make_user, make_membership):
    restaurant = make_restaurant()
    item = make_item(make_category(restaurant), name="Jollof")
    users = {}
    for role in (MembershipRole.OWNER, MembershipRole.MANAGER, MembershipRole.STAFF):
        users[role] = make_user()
        make_membership(restaurant, users[role], role)
    return restaurant, item, users


def item_url(restaurant, item):
    return reverse("staff-menu-item-image", kwargs={"slug": restaurant.slug, "pk": item.pk})


def post(client, url, data):
    return client.post(url, data, format="multipart")


# ---------- menu photos ----------
def test_a_manager_uploads_a_photo_and_customers_see_it(api_client, setup, media):
    restaurant, item, users = setup
    api_client.force_login(users[MembershipRole.MANAGER])
    response = post(api_client, item_url(restaurant, item), upload(picture(), name="../../evil name.png"))
    assert response.status_code == 200
    path = response.json()["image"]
    assert path.startswith(f"/media/restaurants/{restaurant.pk}/menu/") and path.endswith(".webp") and "evil" not in path
    assert os.path.exists(media / path.removeprefix("/media/"))  # the file is on disk
    api_client.logout()
    public = api_client.get(reverse("public-menu", kwargs={"slug": restaurant.slug})).json()
    items = [i for c in public["categories"] for i in c["items"]]
    assert items[0]["image_url"] == path


def test_the_stored_file_is_a_clean_webp_no_larger_than_the_limit(api_client, setup, media):
    restaurant, item, users = setup
    api_client.force_login(users[MembershipRole.OWNER])
    path = post(api_client, item_url(restaurant, item), upload(picture(size=(3000, 2000)))).json()["image"]
    with Image.open(media / path.removeprefix("/media/")) as stored:
        assert stored.format == "WEBP" and max(stored.size) == 1000  # shrunk to the menu size, never enlarged


def test_replacing_and_removing_a_photo_deletes_the_old_file(api_client, setup, media):
    restaurant, item, users = setup
    api_client.force_login(users[MembershipRole.MANAGER])
    first = post(api_client, item_url(restaurant, item), upload(picture())).json()["image"]
    second = post(api_client, item_url(restaurant, item), upload(picture(color="#2980b9"))).json()["image"]
    assert first != second and not os.path.exists(media / first.removeprefix("/media/")) and os.path.exists(media / second.removeprefix("/media/"))
    removed = api_client.delete(item_url(restaurant, item))
    assert removed.status_code == 200 and removed.json()["image"] is None and not os.path.exists(media / second.removeprefix("/media/"))
    assert api_client.delete(item_url(restaurant, item)).status_code == 200  # removing nothing is fine
    assert set(AuditLog.objects.values_list("action", flat=True)) >= {"menu_item.image_changed", "menu_item.image_removed"}


@pytest.mark.parametrize("data, name, content_type, expected", [
    (b"just some text pretending to be a picture", "a.png", "image/png", "isn't a picture"),
    (b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "a.gif", "image/gif", "JPEG, PNG or WebP"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "a.svg", "image/svg+xml", "isn't a picture"),
])
def test_files_that_are_not_real_jpeg_png_or_webp_are_refused(api_client, setup, data, name, content_type, expected):
    restaurant, item, users = setup
    api_client.force_login(users[MembershipRole.OWNER])
    response = post(api_client, item_url(restaurant, item), upload(data, name, content_type))
    assert response.status_code == 400 and expected in response.json()["error"]["details"]["file"][0]
    item.refresh_from_db()
    assert not item.image


def test_oversized_and_missing_uploads_are_refused(api_client, setup, settings):
    restaurant, item, users = setup
    api_client.force_login(users[MembershipRole.OWNER])
    settings.MAX_IMAGE_UPLOAD_BYTES = 200
    assert "too large" in post(api_client, item_url(restaurant, item), upload(picture(size=(300, 300)))).json()["error"]["details"]["file"][0]
    assert post(api_client, item_url(restaurant, item), {}).status_code == 400


def test_only_managers_and_owners_can_change_photos_and_only_for_their_own_restaurant(api_client, setup, make_restaurant, make_category, make_item):
    restaurant, item, users = setup
    assert post(api_client, item_url(restaurant, item), upload(picture())).status_code == 401
    api_client.force_login(users[MembershipRole.STAFF])
    assert post(api_client, item_url(restaurant, item), upload(picture())).status_code == 403
    api_client.force_login(users[MembershipRole.MANAGER])
    other = make_item(make_category(make_restaurant()), name="Theirs")
    assert post(api_client, reverse("staff-menu-item-image", kwargs={"slug": restaurant.slug, "pk": other.pk}), upload(picture())).status_code == 404


def test_archived_items_cannot_get_new_photos(api_client, setup):
    restaurant, item, users = setup
    item.archive()
    api_client.force_login(users[MembershipRole.OWNER])
    assert post(api_client, item_url(restaurant, item), upload(picture())).status_code == 409


def test_an_older_photo_link_still_shows_until_a_photo_is_uploaded(api_client, setup):
    restaurant, item, users = setup
    item.image_url = "https://cdn.example.com/rice.jpg"
    item.save()
    menu = reverse("public-menu", kwargs={"slug": restaurant.slug})
    pick = lambda: [i for c in api_client.get(menu).json()["categories"] for i in c["items"]][0]["image_url"]  # noqa: E731
    assert pick() == "https://cdn.example.com/rice.jpg"
    api_client.force_login(users[MembershipRole.OWNER])
    path = post(api_client, item_url(restaurant, item), upload(picture())).json()["image"]
    api_client.logout()
    assert pick() == path


# ---------- restaurant logo and cover ----------
@pytest.mark.parametrize("route, field, longest", [("restaurant-logo", "logo_url", 512), ("restaurant-cover", "cover_url", 1600)])
def test_a_manager_sets_the_logo_and_cover_shown_on_the_public_page(api_client, setup, media, route, field, longest):
    restaurant, _, users = setup
    api_client.force_login(users[MembershipRole.MANAGER])
    url = reverse(route, kwargs={"slug": restaurant.slug})
    response = post(api_client, url, upload(picture(size=(3000, 1200))))
    assert response.status_code == 200
    path = response.json()[field]
    assert path.startswith(f"/media/restaurants/{restaurant.pk}/")
    with Image.open(media / path.removeprefix("/media/")) as stored:
        assert max(stored.size) == longest
    api_client.logout()
    assert api_client.get(reverse("public-restaurant", kwargs={"slug": restaurant.slug})).json()[field] == path
    api_client.force_login(users[MembershipRole.MANAGER])
    assert api_client.delete(url).json()[field] is None and not os.path.exists(media / path.removeprefix("/media/"))


def test_staff_cannot_change_the_restaurant_pictures_and_other_restaurants_are_untouched(api_client, setup, make_restaurant):
    restaurant, _, users = setup
    api_client.force_login(users[MembershipRole.STAFF])
    assert post(api_client, reverse("restaurant-logo", kwargs={"slug": restaurant.slug}), upload(picture())).status_code == 403
    other = make_restaurant()
    api_client.force_login(users[MembershipRole.OWNER])
    assert post(api_client, reverse("restaurant-logo", kwargs={"slug": other.slug}), upload(picture())).status_code in (403, 404)


def test_uploaded_pictures_are_served_in_development_even_without_debug(settings, tmp_path):
    from django.test import RequestFactory

    from config.urls import media_urlpatterns

    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / "restaurants").mkdir()
    (tmp_path / "restaurants" / "logo.webp").write_bytes(b"RIFFxxxxWEBP")
    settings.DEBUG = False

    settings.SERVE_MEDIA_FILES = False
    assert media_urlpatterns() == []  # production: the web server does this

    settings.SERVE_MEDIA_FILES = True
    (pattern,) = media_urlpatterns()
    match = pattern.resolve("media/restaurants/logo.webp")
    assert match is not None
    response = match.func(RequestFactory().get("/media/restaurants/logo.webp"), **match.kwargs)
    assert response.status_code == 200 and b"".join(response.streaming_content) == b"RIFFxxxxWEBP"
    escape = pattern.resolve("media/../secret.txt")
    assert escape is None or escape.func(RequestFactory().get("/media/../secret.txt"), **escape.kwargs).status_code == 404
