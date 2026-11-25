"""Automated tests. Still PostgreSQL: the test database is created by pytest-django."""
import os

# Test-only value; it protects nothing and must never be used elsewhere.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-used-outside-automated-tests")

from .base import *  # noqa: E402,F401,F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only

# Off by default so unrelated tests see no extra queries; tests/test_platform_middleware.py turns them on.
PLATFORM_ENFORCE_SUBSCRIPTIONS = False
PLATFORM_METER_REQUESTS = False
PLATFORM_ENFORCE_API_KEYS = False
PLATFORM_AUTO_TRIAL = False
SELF_SERVICE = False  # tests that need sign-ups switch it on
MAX_RESTAURANTS_PER_USER = 5
