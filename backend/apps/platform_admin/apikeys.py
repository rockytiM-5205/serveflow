"""API key checks for requests that carry `Authorization: Bearer sf_...` on /api/v1/restaurants/<slug>/ routes.

A request without a key behaves exactly as before: customer routes stay public. A request WITH a key must be
valid, belong to that restaurant, and stay inside the key's limits. Keys are secrets for servers, so test keys
can read but never change data. Per-minute counters live in the cache; with several workers use a shared cache
(Redis) or the effective limit is per worker."""
import time

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone

from .models import ApiCredential, ApiCredentialMonthlyUsage
from .services import hash_secret, record_rate_limit_event

CACHE_SECONDS = 30
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def bearer_secret(request):
    scheme, _, token = request.META.get("HTTP_AUTHORIZATION", "").partition(" ")
    token = token.strip()
    return token if scheme.lower() == "bearer" and token.startswith("sf_") else None


def _key(secret_hash):
    return f"platform:key:{secret_hash}"


def forget(secret_hash):
    cache.delete(_key(secret_hash))


def _lookup(secret):
    digest = hash_secret(secret)
    state = cache.get(_key(digest))
    if state is None:
        row = ApiCredential.objects.filter(secret_hash=digest).values(
            "id", "restaurant_id", "status", "environment", "rate_limit_per_minute", "monthly_request_limit",
            "restaurant__subscription__plan__rate_limit_per_minute", "restaurant__subscription__plan__included_requests").first()
        if row:
            # A key's own numbers win; otherwise it follows the restaurant's current plan. No plan means no limit.
            plan_rate = row.pop("restaurant__subscription__plan__rate_limit_per_minute")
            plan_allowance = row.pop("restaurant__subscription__plan__included_requests")
            if row["rate_limit_per_minute"] is None:
                row["rate_limit_per_minute"] = plan_rate
            if row["monthly_request_limit"] is None:
                row["monthly_request_limit"] = plan_allowance
        state = row or {}
        cache.set(_key(digest), state, CACHE_SECONDS)
    return state


def _error(status, code, message, headers=None):
    response = JsonResponse({"error": {"code": code, "message": message, "details": {}}}, status=status)
    for name, value in (headers or {}).items():
        response[name] = value
    return response


def count_month(credential_id, today=None):
    """Atomically add one request to this key's month and return the new total."""
    month = (today or timezone.localdate()).replace(day=1)
    table = connection.ops.quote_name(ApiCredentialMonthlyUsage._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {table} (credential_id, month, requests) VALUES (%s, %s, 1) "
            f"ON CONFLICT (credential_id, month) DO UPDATE SET requests = {table}.requests + 1 RETURNING requests",
            [credential_id, month],
        )
        return cursor.fetchone()[0]


def authorize(request, secret, restaurant_state):
    """None when the request may go on, otherwise the error response to send. Sets request.platform_credential_id."""
    credential = _lookup(secret)
    if not credential or credential["status"] != ApiCredential.Status.ACTIVE:
        return _error(401, "invalid_api_key", "That API key isn't valid. It may have been revoked.", {"WWW-Authenticate": "Bearer"})
    if restaurant_state.get("id") != credential["restaurant_id"]:
        return _error(403, "api_key_wrong_restaurant", "This API key doesn't belong to this restaurant.")
    if credential["environment"] == ApiCredential.Environment.TEST and request.method not in SAFE_METHODS:
        return _error(403, "test_key_read_only", "Test keys can read data but can't change it.")

    limit = credential["rate_limit_per_minute"]
    if limit:
        window = int(time.time() // 60)
        counter = f"platform:rate:{credential['id']}:{window}"
        cache.add(counter, 0, 70)
        if cache.incr(counter) > limit:
            record_rate_limit_event(credential["restaurant_id"], request.resolver_match.route[:200], f"{limit}/min", credential["id"])
            request.platform_event_logged = True
            return _error(429, "rate_limited", "Too many requests for this API key. Slow down and retry.", {"Retry-After": str(60 - int(time.time()) % 60)})

    used = count_month(credential["id"])
    allowance = credential["monthly_request_limit"]
    if allowance is not None and used > allowance:
        record_rate_limit_event(credential["restaurant_id"], request.resolver_match.route[:200], f"{allowance}/month", credential["id"])
        request.platform_event_logged = True
        return _error(429, "monthly_quota_exceeded", "This API key has used its monthly request allowance.")

    if cache.add(f"platform:key-used:{credential['id']}", 1, 60):  # touch last_used_at at most once a minute
        ApiCredential.objects.filter(pk=credential["id"]).update(last_used_at=timezone.now())
    request.platform_credential_id = credential["id"]
    return None



