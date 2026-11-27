"""Throttles that identify a caller by a network address the caller cannot choose.

DRF's own `get_ident()` trusts the whole X-Forwarded-For header when no proxy count is configured, so a client can reset any per-IP
limit just by sending a different header on every request. These classes instead ask settings.TRUSTED_PROXY_COUNT (env
DJANGO_NUM_PROXIES): with 0 the header is ignored and the connecting address is used; with N the address N entries from the right is used
(the entries a proxy of ours added, never what the client wrote). See docs/deploy.md.
"""
from django.conf import settings
from rest_framework import throttling


def client_ip(request) -> str:
    meta = request.META
    remote = meta.get("REMOTE_ADDR", "")
    proxies = int(getattr(settings, "TRUSTED_PROXY_COUNT", 0) or 0)
    addrs = [part.strip() for part in meta.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
    if proxies < 1 or not addrs:
        return remote
    return addrs[-min(proxies, len(addrs))]


class _TrustedIdent:
    def get_ident(self, request):
        return client_ip(request)


class ScopedRateThrottle(_TrustedIdent, throttling.ScopedRateThrottle):
    """Drop-in for rest_framework's ScopedRateThrottle."""


class SimpleRateThrottle(_TrustedIdent, throttling.SimpleRateThrottle):
    """Drop-in base class for the custom throttles."""


class GlobalThrottle(throttling.SimpleRateThrottle):
    """One shared counter for everybody, whatever address they claim. A backstop for sign-ups that does not depend on knowing the
    caller's IP. Set `scope` on the subclass and add its rate to DEFAULT_THROTTLE_RATES."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": "all"}


class SignupGlobalThrottle(GlobalThrottle):
    scope = "signup_global"


class CustomerSignupGlobalThrottle(GlobalThrottle):
    scope = "customer_signup_global"
