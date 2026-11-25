"""Three jobs for every /api/v1/restaurants/<slug>/... request:

1. Subscription lock. A restaurant whose subscription is EXPIRED or CANCELLED is locked: customers (anonymous
   callers) get 402 on everything, and signed-in staff get 402 on anything that changes data but can still read
   their own dashboard. Restaurants with no subscription at all are never locked, and PAST_DUE (the grace
   period) is not locked. Platform owners (superusers) are exempt.
2. API keys. A request carrying `Authorization: Bearer sf_...` is checked by apikeys.py (valid, same restaurant,
   within its rate limit and monthly allowance). Requests without a key are unchanged.
3. Metering. One counted request per restaurant, day, method and route pattern, feeding the owner usage pages.
   Metering never breaks a response: any failure is logged and ignored.

Both can be switched off with PLATFORM_ENFORCE_SUBSCRIPTIONS and PLATFORM_METER_REQUESTS.
"""
import logging

from django.conf import settings
from django.http import JsonResponse

from . import apikeys, locks, services

logger = logging.getLogger(__name__)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class PlatformMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(settings, "PLATFORM_METER_REQUESTS", True):
            self._meter(request, response)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        slug = view_kwargs.get("slug")
        if not slug:
            return None
        secret = apikeys.bearer_secret(request)
        if secret and getattr(settings, "PLATFORM_ENFORCE_API_KEYS", True):
            rejected = apikeys.authorize(request, secret, locks.get_state(slug))
            if rejected:
                return rejected
        if not getattr(settings, "PLATFORM_ENFORCE_SUBSCRIPTIONS", True):
            return None
        if (request.resolver_match.url_name or "").startswith("billing-"):
            return None  # a locked restaurant must still be able to see its plan and pay
        user = request.user
        if user.is_authenticated and user.is_superuser:
            return None
        if not locks.get_state(slug).get("locked"):
            return None
        if user.is_authenticated and request.method in SAFE_METHODS:
            return None  # staff can still look at their dashboard
        message = (
            "Your ServeFlow subscription has ended. Renew it to make changes."
            if user.is_authenticated
            else "This restaurant isn't taking orders through ServeFlow right now."
        )
        return JsonResponse({"error": {"code": "subscription_inactive", "message": message, "details": {}}}, status=402)

    def _meter(self, request, response):
        try:
            match = request.resolver_match
            slug = match.kwargs.get("slug") if match else None
            if not slug:
                return  # unknown routes are skipped so a scanner can't create endless rows
            state = locks.get_state(slug)
            if not state:
                return
            route = "/" + match.route.lstrip("/")
            services.record_usage(state["id"], request.method, route, error=response.status_code >= 500)
            if response.status_code == 429 and not getattr(request, "platform_event_logged", False):
                services.record_rate_limit_event(state["id"], route, "throttled")
        except Exception:  # noqa: BLE001 - metering must never fail a request
            logger.exception("Request metering failed")
