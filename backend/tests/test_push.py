"""Order alerts on staff devices. The push service itself is never called: sending is replaced by a stand-in. Needs PostgreSQL."""
import pytest
from django.urls import reverse

from apps.restaurants import push
from apps.restaurants.models import MembershipRole, PushSubscription

pytestmark = pytest.mark.django_db
STAFF = MembershipRole.STAFF
DEVICE = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123", "p256dh": "BPpublickey", "auth": "authsecret"}


def url(name, shop):
    return reverse(name, kwargs={"slug": shop.restaurant.slug})


@pytest.fixture
def vapid(settings):
    settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY, settings.VAPID_SUBJECT = "PUBKEY", "PRIVKEY", "mailto:ops@example.com"


def test_alerts_are_reported_off_until_the_keys_are_set(api_client, shop, staff_login):
    staff_login(shop.restaurant, STAFF)
    body = api_client.get(url("restaurant-push-config", shop)).json()
    assert body == {"enabled": False, "public_key": "", "devices": 0}


def test_the_public_key_is_given_once_alerts_are_on(api_client, shop, staff_login, vapid):
    staff_login(shop.restaurant, STAFF)
    body = api_client.get(url("restaurant-push-config", shop)).json()
    assert body["enabled"] is True and body["public_key"] == "PUBKEY" and "PRIVKEY" not in str(body)


def test_staff_can_turn_alerts_on_and_off_for_a_device(api_client, shop, staff_login):
    user = staff_login(shop.restaurant, STAFF)
    assert api_client.post(url("restaurant-push-subscribe", shop), DEVICE, format="json").json() == {"subscribed": True}
    stored = PushSubscription.objects.get()
    assert (stored.user, stored.restaurant, stored.endpoint) == (user, shop.restaurant, DEVICE["endpoint"])
    assert api_client.get(url("restaurant-push-config", shop)).json()["devices"] == 1
    assert api_client.post(url("restaurant-push-unsubscribe", shop), {"endpoint": DEVICE["endpoint"]}, format="json").json() == {"subscribed": False}
    assert PushSubscription.objects.count() == 0


def test_turning_alerts_on_again_updates_the_device_instead_of_adding_one(api_client, shop, staff_login):
    staff_login(shop.restaurant, STAFF)
    api_client.post(url("restaurant-push-subscribe", shop), DEVICE, format="json")
    api_client.post(url("restaurant-push-subscribe", shop), {**DEVICE, "auth": "newsecret"}, format="json")
    assert PushSubscription.objects.count() == 1 and PushSubscription.objects.get().auth == "newsecret"


@pytest.mark.parametrize("endpoint", ["http://push.example.com/x", "javascript:alert(1)", "not a url", ""])
def test_only_https_push_addresses_are_accepted(api_client, shop, staff_login, endpoint):
    staff_login(shop.restaurant, STAFF)
    assert api_client.post(url("restaurant-push-subscribe", shop), {**DEVICE, "endpoint": endpoint}, format="json").status_code == 400
    assert PushSubscription.objects.count() == 0


def test_someone_elses_device_cannot_be_removed(api_client, shop, staff_login, make_user):
    theirs = PushSubscription.objects.create(restaurant=shop.restaurant, user=make_user(), **{k: DEVICE[k] for k in ("endpoint", "p256dh", "auth")})
    staff_login(shop.restaurant, STAFF)
    api_client.post(url("restaurant-push-unsubscribe", shop), {"endpoint": DEVICE["endpoint"]}, format="json")
    assert PushSubscription.objects.filter(pk=theirs.pk).exists()


def test_people_outside_the_restaurant_cannot_use_its_alerts(api_client, shop, staff_login, make_restaurant):
    staff_login(make_restaurant(), STAFF)
    assert api_client.post(url("restaurant-push-subscribe", shop), DEVICE, format="json").status_code in (403, 404)
    assert api_client.get(url("restaurant-push-config", shop)).status_code in (403, 404)
    assert PushSubscription.objects.count() == 0


def test_signed_out_visitors_cannot_subscribe(api_client, shop):
    assert api_client.post(url("restaurant-push-subscribe", shop), DEVICE, format="json").status_code in (401, 403)


# ---------------------------------------------------------------- sending
def make_devices(shop, make_user, n=2):
    return [PushSubscription.objects.create(restaurant=shop.restaurant, user=make_user(), endpoint=f"https://fcm.googleapis.com/fcm/send/{i}", p256dh="k", auth="a") for i in range(n)]


def test_a_device_the_browser_says_is_gone_is_forgotten(shop, make_user, monkeypatch):
    gone, fine = make_devices(shop, make_user)

    def fake(subscription, payload):
        if subscription.pk == gone.pk:
            raise push.PushGone

    monkeypatch.setattr(push, "_deliver", fake)
    assert push.send_to(list(PushSubscription.objects.all()), {"title": "x"}) == 1
    assert list(PushSubscription.objects.values_list("pk", flat=True)) == [fine.pk]


def test_one_failing_device_does_not_stop_the_others_and_is_kept(shop, make_user, monkeypatch):
    broken, fine = make_devices(shop, make_user)

    def fake(subscription, payload):
        if subscription.pk == broken.pk:
            raise RuntimeError("push service had a bad moment")

    monkeypatch.setattr(push, "_deliver", fake)
    assert push.send_to(list(PushSubscription.objects.order_by("pk")), {"title": "x"}) == 1
    assert PushSubscription.objects.count() == 2
    fine.refresh_from_db()
    assert fine.last_success_at is not None


def test_a_new_order_alerts_the_team_with_only_its_reference_and_item_count(shop, place, vapid, monkeypatch, django_capture_on_commit_callbacks):
    sent = []
    monkeypatch.setattr(push, "send_async", lambda restaurant_id, payload: sent.append((restaurant_id, payload)))
    with django_capture_on_commit_callbacks(execute=True):
        assert place(shop.restaurant, [(shop.rice.pk, 2), (shop.beans.pk, 1)]).status_code == 201
    (restaurant_id, payload), = sent
    assert restaurant_id == shop.restaurant.pk
    assert payload["title"].startswith(f"New order {shop.restaurant.order_prefix}-") and payload["body"].startswith("3 items")
    assert set(payload) == {"title", "body", "url", "tag", "icon"} and payload["url"] == "/restaurant-dashboard/orders.html"


def test_no_thread_is_started_while_alerts_are_off(shop, monkeypatch):
    import threading

    monkeypatch.setattr(threading, "Thread", lambda *a, **k: pytest.fail("a thread was started"))
    push.send_async(shop.restaurant.pk, {"title": "x"})


def test_the_test_alert_goes_only_to_my_devices(api_client, shop, staff_login, make_user, vapid, monkeypatch):
    seen = []
    monkeypatch.setattr(push, "_deliver", lambda subscription, payload: seen.append((subscription.endpoint, payload["title"])))
    PushSubscription.objects.create(restaurant=shop.restaurant, user=make_user(), endpoint="https://fcm.googleapis.com/fcm/send/other", p256dh="k", auth="a")
    staff_login(shop.restaurant, STAFF)
    api_client.post(url("restaurant-push-subscribe", shop), DEVICE, format="json")
    assert api_client.post(url("restaurant-push-test", shop)).json() == {"sent": 1, "enabled": True}
    assert seen == [(DEVICE["endpoint"], "ServeFlow alerts are on")]


def test_the_test_alert_says_so_when_alerts_are_off(api_client, shop, staff_login):
    staff_login(shop.restaurant, STAFF)
    assert api_client.post(url("restaurant-push-test", shop)).json() == {"sent": 0, "enabled": False}


@pytest.mark.parametrize("endpoint", [
    "https://127.0.0.1/send", "https://localhost/send", "https://169.254.169.254/latest", "https://internal.example.com/hook",
    "https://fcm.googleapis.com.evil.example/send", "https://user:pw@fcm.googleapis.com/send", "https://fcm.googleapis.com:8443/send",
    "https://evilnotify.windows.com.example/send",
])
def test_only_real_browser_push_services_are_accepted(api_client, shop, staff_login, endpoint):
    staff_login(shop.restaurant)
    response = api_client.post(url("restaurant-push-subscribe", shop), {**DEVICE, "endpoint": endpoint}, format="json")
    assert response.status_code == 400 and not PushSubscription.objects.filter(endpoint=endpoint).exists()


@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc", "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://web.push.apple.com/abc", "https://db5p.notify.windows.com/w/?token=abc",
])
def test_real_browser_push_services_are_accepted(api_client, shop, staff_login, endpoint):
    staff_login(shop.restaurant)
    assert api_client.post(url("restaurant-push-subscribe", shop), {**DEVICE, "endpoint": endpoint}, format="json").status_code == 200


def test_a_stored_device_with_a_non_push_address_is_never_contacted_and_is_forgotten(shop, make_user, monkeypatch):
    from apps.restaurants import push

    bad = PushSubscription.objects.create(restaurant=shop.restaurant, user=make_user(), endpoint="https://internal.example.com/x", p256dh="k", auth="a")
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kw: sent.append(kw), raising=False)
    push.send_to([bad], {"title": "t"})
    assert sent == [] and not PushSubscription.objects.filter(pk=bad.pk).exists()


def test_one_person_cannot_register_an_unlimited_number_of_devices(api_client, shop, staff_login):
    from apps.restaurants.push_views import MAX_DEVICES

    staff_login(shop.restaurant)
    for i in range(MAX_DEVICES):
        assert api_client.post(url("restaurant-push-subscribe", shop), {**DEVICE, "endpoint": f"https://fcm.googleapis.com/fcm/send/{i}"}, format="json").status_code == 200
    assert api_client.post(url("restaurant-push-subscribe", shop), {**DEVICE, "endpoint": "https://fcm.googleapis.com/fcm/send/extra"}, format="json").status_code == 400
