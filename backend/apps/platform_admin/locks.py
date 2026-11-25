"""Per-restaurant state the middleware needs on every API call: its id and whether it is locked.
A restaurant is locked when its subscription is EXPIRED or CANCELLED, OR when the dates say it should be, even if
`sync_subscriptions` hasn't run yet: a trial is locked the moment it ends (no grace), and a paid subscription
BILLING_GRACE_DAYS after its period ends. Restaurants with no subscription at all are not locked.
Cached for a short time so the check costs no database query on most requests. The cache is per process (see
CACHES in settings), so another worker can take up to CACHE_SECONDS to notice a change."""
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.restaurants.models import Restaurant

from .models import Subscription

CACHE_SECONDS = 30
LOCKED_STATUSES = (Subscription.Status.EXPIRED, Subscription.Status.CANCELLED)


def _key(slug):
    return f"platform:restaurant:{slug}"


def is_locked(status, period_end, now=None):
    now = now or timezone.now()
    if status in LOCKED_STATUSES:
        return True
    if status is None or period_end is None:
        return False
    if status == Subscription.Status.TRIAL:
        return period_end < now
    if status in (Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE):
        return period_end + timedelta(days=getattr(settings, "BILLING_GRACE_DAYS", 3)) < now
    return False


def get_state(slug):
    """{"id": int, "locked": bool}, or {} when no such restaurant exists."""
    state = cache.get(_key(slug))
    if state is None:
        row = Restaurant.objects.filter(slug=slug).values("id", "subscription__status", "subscription__current_period_end").first()
        state = {} if row is None else {"id": row["id"], "locked": is_locked(row["subscription__status"], row["subscription__current_period_end"])}
        cache.set(_key(slug), state, CACHE_SECONDS)
    return state


def forget(slug):
    cache.delete(_key(slug))
