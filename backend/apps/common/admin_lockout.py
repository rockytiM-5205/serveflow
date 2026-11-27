"""Brute-force protection for the Django admin login (the API's throttles do not cover it).

Counts FAILED admin sign-ins per username and per address. Once either passes its limit the admin login answers 429 for the rest of the
window, even for the right password, so guessing gains nothing. A successful sign-in clears that username's counter. Counters live in
the cache (per process; see docs/deploy.md). Wired in by apps.common.admin_lockout.AdminLoginLockoutMiddleware.
"""
import hashlib

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver
from django.http import HttpResponse

from .throttles import client_ip


def _login_path() -> str:
    return "/" + settings.ADMIN_URL + "login/"


def _keys(request, username):
    user = hashlib.sha256((username or "").strip().lower().encode()).hexdigest()[:32]
    return f"adminlock:user:{user}", f"adminlock:ip:{client_ip(request)}"


def _count(key) -> int:
    return int(cache.get(key, 0) or 0)


def _bump(key):
    window = settings.ADMIN_LOCKOUT_SECONDS
    if cache.add(key, 1, window):
        return
    try:
        cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.add(key, 1, window)


class AdminLoginLockoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.path == _login_path():
            user_key, ip_key = _keys(request, request.POST.get("username", ""))
            if _count(user_key) >= settings.ADMIN_LOCKOUT_FAILURES or _count(ip_key) >= settings.ADMIN_LOCKOUT_IP_FAILURES:
                return HttpResponse("Too many failed sign-in attempts. Try again later.", status=429, content_type="text/plain")
        return self.get_response(request)


@receiver(user_login_failed)
def _count_failure(sender, credentials, request=None, **kwargs):
    if request is None or request.path != _login_path():
        return
    user_key, ip_key = _keys(request, (credentials or {}).get("username", ""))
    _bump(user_key)
    _bump(ip_key)


@receiver(user_logged_in)
def _clear_on_success(sender, request=None, user=None, **kwargs):
    if request is not None and request.path == _login_path() and user is not None:
        cache.delete(_keys(request, getattr(user, "email", ""))[0])
