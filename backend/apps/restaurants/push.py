"""Order alerts on staff phones and tablets (Web Push). Switched off until the VAPID keys are set (see generate_vapid_keys).

Sending happens in a background thread after the order has been saved, so a slow push service can never delay a customer's checkout.
A device the browser says is gone (404 or 410) is forgotten. Alerts carry only the order reference and the number of items."""
import json
import time
import logging
import threading
from urllib.parse import urlparse

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import PushSubscription

log = logging.getLogger(__name__)
DASHBOARD_ORDERS = "/restaurant-dashboard/orders.html"
ICON = "/shared/assets/icons/icon-192.png"


# Only the push services that browsers use. A device address is a URL the server will POST to, so anything else (an internal host, a
# stranger's server) would let a signed-in user make this server send requests wherever they like. Add more with the
# DJANGO_PUSH_EXTRA_HOSTS setting (comma-separated host names) if a browser vendor adds a service.
PUSH_HOSTS = frozenset({"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"})
PUSH_HOST_SUFFIXES = (".push.services.mozilla.com", ".push.apple.com", ".notify.windows.com")


def is_push_service(url: str) -> bool:
    """True only for an https address on a known browser push service: default port, no credentials, no IP address."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443) or not host:
        return False
    extra = {h.strip().lower() for h in getattr(settings, "PUSH_EXTRA_HOSTS", []) if h.strip()}
    return host in PUSH_HOSTS or host in extra or host.endswith(PUSH_HOST_SUFFIXES)


class PushGone(Exception):
    """The browser says this device no longer exists."""


def enabled():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY and settings.VAPID_SUBJECT)


def _deliver(subscription, payload):
    """Send one message to one device. Raises PushGone if the device is gone; other failures raise their own error."""
    if not is_push_service(subscription.endpoint):
        raise PushGone()  # never POST to an address that isn't a push service; the stored device is forgotten
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # the package isn't installed: alerts stay off rather than breaking orders
        raise RuntimeError("pywebpush is not installed") from None
    try:
        webpush(
            subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=json.dumps(payload), vapid_private_key=settings.VAPID_PRIVATE_KEY, vapid_claims={"sub": settings.VAPID_SUBJECT}, ttl=3600,
            headers={"Urgency": "high"},  # new orders must wake a phone that is resting, not wait for it to wake up on its own
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushGone from exc
        raise


def send_report(subscriptions, payload):
    """Send to each subscription, forgetting the ones that are gone. Returns what happened:
    {"devices", "delivered", "gone", "failed", "status"}; status is the push service's HTTP status for the last failure, if it gave one."""
    report = {"devices": len(subscriptions), "delivered": 0, "gone": 0, "failed": 0, "status": None}
    for subscription in subscriptions:
        try:
            _deliver(subscription, payload)
        except PushGone:
            subscription.delete()
            report["gone"] += 1
        except Exception as exc:  # noqa: BLE001 - one bad device must not stop the others
            report["failed"] += 1
            report["status"] = getattr(getattr(exc, "response", None), "status_code", None)
            log.warning("Push to device %s failed: %s", subscription.pk, exc, exc_info=True)
        else:
            report["delivered"] += 1
            PushSubscription.objects.filter(pk=subscription.pk).update(last_success_at=timezone.now())
    return report


def send_to(subscriptions, payload):
    """Send to each subscription. Returns how many were delivered."""
    return send_report(subscriptions, payload)["delivered"]


def _send_all(restaurant_id, payload):
    try:
        report = send_report(list(PushSubscription.objects.filter(restaurant_id=restaurant_id)), payload)
        # One plain line per alert, so the server log shows exactly what happened (devices known, delivered, refused).
        (log.info if report["delivered"] else log.warning)("Order alert for restaurant %s: %s", restaurant_id, report)
    finally:
        connection.close()  # this thread opened its own database connection


def _send_after(subscription_ids, payload, delay):
    try:
        time.sleep(delay)
        send_report(list(PushSubscription.objects.filter(pk__in=subscription_ids)), payload)
    finally:
        connection.close()


def send_later(subscriptions, payload, delay):
    """Send after `delay` seconds from a background thread: lets someone close the app first and prove that alerts arrive without it."""
    threading.Thread(target=_send_after, args=([s.pk for s in subscriptions], payload, delay), daemon=True).start()


def send_async(restaurant_id, payload):
    if not enabled():
        log.warning("Order alerts are OFF on this server: VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_SUBJECT must all be set.")
        return
    threading.Thread(target=_send_all, args=(restaurant_id, payload), daemon=True).start()


def notify_new_order(restaurant_id, reference, item_count):
    send_async(restaurant_id, {
        "title": f"New order {reference}",
        "body": f"{item_count} item{'' if item_count == 1 else 's'}. Tap to open your orders.",
        "url": DASHBOARD_ORDERS, "tag": "new-order", "icon": ICON,
    })
