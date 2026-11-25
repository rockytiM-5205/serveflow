"""Order alerts on staff phones and tablets (Web Push). Switched off until the VAPID keys are set (see generate_vapid_keys).

Sending happens in a background thread after the order has been saved, so a slow push service can never delay a customer's checkout.
A device the browser says is gone (404 or 410) is forgotten. Alerts carry only the order reference and the number of items."""
import json
import logging
import threading

from django.conf import settings
from django.db import connection
from django.utils import timezone

from .models import PushSubscription

log = logging.getLogger(__name__)
DASHBOARD_ORDERS = "/restaurant-dashboard/orders.html"
ICON = "/shared/assets/icons/icon-192.png"


class PushGone(Exception):
    """The browser says this device no longer exists."""


def enabled():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY and settings.VAPID_SUBJECT)


def _deliver(subscription, payload):
    """Send one message to one device. Raises PushGone if the device is gone; other failures raise their own error."""
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:  # the package isn't installed: alerts stay off rather than breaking orders
        raise RuntimeError("pywebpush is not installed") from None
    try:
        webpush(
            subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=json.dumps(payload), vapid_private_key=settings.VAPID_PRIVATE_KEY, vapid_claims={"sub": settings.VAPID_SUBJECT}, ttl=3600,
        )
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            raise PushGone from exc
        raise


def send_to(subscriptions, payload):
    """Send to each subscription, forgetting the ones that are gone. Returns how many were delivered."""
    delivered = 0
    for subscription in subscriptions:
        try:
            _deliver(subscription, payload)
        except PushGone:
            subscription.delete()
        except Exception:  # noqa: BLE001 - one bad device must not stop the others
            log.warning("Push to %s failed", subscription.pk, exc_info=True)
        else:
            delivered += 1
            PushSubscription.objects.filter(pk=subscription.pk).update(last_success_at=timezone.now())
    return delivered


def _send_all(restaurant_id, payload):
    try:
        send_to(list(PushSubscription.objects.filter(restaurant_id=restaurant_id)), payload)
    finally:
        connection.close()  # this thread opened its own database connection


def send_async(restaurant_id, payload):
    if enabled():
        threading.Thread(target=_send_all, args=(restaurant_id, payload), daemon=True).start()


def notify_new_order(restaurant_id, reference, item_count):
    send_async(restaurant_id, {
        "title": f"New order {reference}",
        "body": f"{item_count} item{'' if item_count == 1 else 's'}. Tap to open your orders.",
        "url": DASHBOARD_ORDERS, "tag": "new-order", "icon": ICON,
    })
