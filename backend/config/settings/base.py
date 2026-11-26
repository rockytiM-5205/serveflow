"""Settings shared by every environment. Environment-specific modules extend this."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import env, require

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/

_DB_HINT = "ServeFlow requires PostgreSQL; there is no SQLite fallback."

# --- Core security -----------------------------------------------------------
SECRET_KEY = require("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
# Platform admin lives at a configurable path; set a non-default value in production.
ADMIN_URL = env.str("DJANGO_ADMIN_URL", default="admin/").strip("/") + "/"

# --- Self-service onboarding --------------------------------------------------
# When on, anyone can create an account and a restaurant from the dashboard (no Django admin
# needed). Off by default: turn it on deliberately, because public sign-up invites spam.
# Anyone can sign up and create ONE restaurant, which starts a free trial (see PLATFORM_AUTO_TRIAL). Set DJANGO_SELF_SERVICE=false
# to close sign-ups; the platform owner can still create restaurants and their admins from the Owner Control Centre.
SELF_SERVICE = env.bool("DJANGO_SELF_SERVICE", default=True)
MAX_RESTAURANTS_PER_USER = 1

# --- Applications ------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "drf_spectacular",
    # ServeFlow
    "apps.accounts",
    "apps.restaurants",
    "apps.menu",
    "apps.audit",
    "apps.orders",
    "apps.platform_admin",
    "apps.marketplace",
    "apps.reviews",
    "apps.customers",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.platform_admin.middleware.PlatformMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database: PostgreSQL only -----------------------------------------------
# Hosted (Neon, Render, ...): set DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
# Local development: leave DATABASE_URL unset and use the POSTGRES_* variables in .env.
if os.environ.get("DATABASE_URL", "").strip():
    _default_db = env.db("DATABASE_URL")
    if not _default_db["ENGINE"].endswith("postgresql"):
        raise ImproperlyConfigured(f"DATABASE_URL must be a PostgreSQL URL. {_DB_HINT}")
    _default_db["CONN_MAX_AGE"] = env.int("DJANGO_DB_CONN_MAX_AGE", default=60)
    _default_db["CONN_HEALTH_CHECKS"] = True
    # Neon's pooled address (host contains "-pooler") runs PgBouncer in transaction mode: no server-side cursors and no
    # server-side prepared statements. Set DJANGO_DB_POOLED=True for any other PgBouncer.
    if "-pooler" in _default_db.get("HOST", "") or env.bool("DJANGO_DB_POOLED", default=False):
        _default_db["DISABLE_SERVER_SIDE_CURSORS"] = True
        _default_db.setdefault("OPTIONS", {})["prepare_threshold"] = None
    DATABASES = {"default": _default_db}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": require("POSTGRES_DB", _DB_HINT),
            "USER": require("POSTGRES_USER", _DB_HINT),
            "PASSWORD": require("POSTGRES_PASSWORD", _DB_HINT),
            "HOST": env("POSTGRES_HOST", default="localhost"),
            "PORT": env("POSTGRES_PORT", default="5432"),
        }
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication ----------------------------------------------------------
# The custom email-login User is implemented in the next stage. It must exist
# (with its first migration) before any other app migrates.
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalisation and time ------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"  # Stored times are UTC; restaurants carry their own timezone.
USE_I18N = True
USE_TZ = True

# --- Static files ------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded pictures (restaurant logo and cover, menu photos). Every upload is checked and re-encoded as WebP (apps/common/images.py).
# In production serve MEDIA_ROOT from your web server or object storage under MEDIA_URL; Django only serves it in development.
MEDIA_URL = "/media/"
MEDIA_ROOT = env("DJANGO_MEDIA_ROOT", default=str(BASE_DIR / "media"))
# Let Django serve MEDIA_ROOT itself. On for local development (development.py), off everywhere else.
SERVE_MEDIA_FILES = False
MAX_IMAGE_UPLOAD_BYTES = 3 * 1024 * 1024

# --- Django REST Framework ---------------------------------------------------
# Deny by default: public endpoints must opt in with AllowAny and
# authentication_classes = [] explicitly.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.common.authentication.CsrfSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    # How many reverse proxies sit in front of Django (Vercel + Render = 2). With 0 the throttles trust the whole
    # X-Forwarded-For header, which a client can fake; set DJANGO_NUM_PROXIES in production (see docs/deploy.md).
    "NUM_PROXIES": env.int("DJANGO_NUM_PROXIES", default=0) or None,
    "DEFAULT_THROTTLE_RATES": {
        "login_ip": "5/min",
        "login_email": "5/min",
        "signup": "10/hour",
        "restaurant_create": "10/hour",
        "password_change": "5/min",
        "order_create": "30/min",
        "order_phone": "20/hour",
        "order_lookup": "600/min",
        "order_cancel": "10/min",
        "payment_webhook": "300/min",
        "marketplace": "120/min",
        "customer_signup": "20/hour",
    },
}

# Throttle counters live in the cache. LocMemCache is per process: with several
# workers each keeps its own count, so limits are weaker than they look. Use a shared
# cache (Redis, or Django's database cache) before running more than one worker.
# Platform owner features (apps.platform_admin): lock restaurants whose subscription ended, and count API requests.
PLATFORM_ENFORCE_SUBSCRIPTIONS = True
PLATFORM_METER_REQUESTS = True
PLATFORM_ENFORCE_API_KEYS = True
# Refuse NEW orders (code ORDER_LIMIT_REACHED) once a restaurant's completed orders reach its allowance. Leave on.
PLATFORM_ENFORCE_ORDER_LIMITS = True
# Pickup orders: the earliest time a customer can choose is this many minutes ahead (a few minutes of slack are allowed so
# a customer still filling in the form isn't refused), in steps of PICKUP_SLOT_MINUTES, up to PICKUP_MAX_HOURS ahead.
PICKUP_MIN_LEAD_MINUTES = 30
PICKUP_LEAD_SLACK_MINUTES = 5
PICKUP_SLOT_MINUTES = 15
PICKUP_MAX_HOURS = 48
# Shared secret that signs payment-provider webhooks (HMAC-SHA256 of the raw body, hex, in the X-Signature header).
# Empty means webhooks are switched off: the endpoint answers 503 and confirms nothing. Never commit a real value.
PAYMENT_WEBHOOK_SECRET = env("PAYMENT_WEBHOOK_SECRET", default="")
# Order alerts on staff devices (Web Push). Empty keys switch alerts off. Make a pair with: python manage.py generate_vapid_keys
# The private key is a secret: never commit it. VAPID_SUBJECT is a contact address, e.g. mailto:you@example.com.
VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = env("VAPID_PRIVATE_KEY", default="")
VAPID_SUBJECT = env("VAPID_SUBJECT", default="")
# A new restaurant gets a 2-day free trial and is locked the moment it ends (no grace). Paid subscriptions that
# lapse get BILLING_GRACE_DAYS before they lock.
BILLING_TRIAL_DAYS = 2
BILLING_GRACE_DAYS = 3
PLATFORM_AUTO_TRIAL = True

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

SPECTACULAR_SETTINGS = {
    "TITLE": "ServeFlow API",
    "DESCRIPTION": "Multi-tenant restaurant ordering API.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
}

# Print server errors (with tracebacks) to the terminal even when DEBUG is off.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False}},
}
