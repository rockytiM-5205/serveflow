"""Production. Refuses to start with unsafe configuration."""
import os

from django.core.exceptions import ImproperlyConfigured

from config.env import env

from .base import *  # noqa: F401,F403

# Render tells every web service its own public host name; trust it automatically so the service can answer its health
# check and requests proxied from the frontend. Add your own domain to DJANGO_ALLOWED_HOSTS if you attach one.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host and _render_host not in ALLOWED_HOSTS:  # noqa: F405
    ALLOWED_HOSTS.append(_render_host)  # noqa: F405

if DEBUG:  # noqa: F405
    raise ImproperlyConfigured("DJANGO_DEBUG must not be enabled in production.")
if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list the production host names.")
if (
    SECRET_KEY.startswith(("change-me", "django-insecure-", "test-only"))  # noqa: F405
    or len(SECRET_KEY) < 50  # noqa: F405
):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY looks like a placeholder or is too short; generate a real one (see .env.example)."
    )

SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
X_FRAME_OPTIONS = "DENY"

# Start low and raise deliberately once HTTPS is confirmed; HSTS is hard to undo.
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Only enable behind a trusted reverse proxy that sets and sanitises this header.
if env.bool("DJANGO_TRUST_PROXY_SSL_HEADER", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Uploaded pictures. Preferred: Cloudinary. Set CLOUDINARY_URL (cloudinary://API_KEY:API_SECRET@CLOUD_NAME) and every upload is stored there
# and served from Cloudinary's CDN (see below), so nothing is lost when Render redeploys.
# Fallback without Cloudinary: Render's disk is wiped on every deploy unless a persistent disk is attached, so set DJANGO_MEDIA_ROOT to the
# disk's mount path (for example /var/data/media) and DJANGO_SERVE_MEDIA=True to let Django serve it. Off by default.
SERVE_MEDIA_FILES = env.bool("DJANGO_SERVE_MEDIA", default=False)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]  # the host's health check calls this over plain HTTP

# Static files (Django admin, API docs) are served by WhiteNoise from the same process. Run `collectstatic` at build time.
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

if os.environ.get("CLOUDINARY_URL", "").strip():
    STORAGES["default"] = {"BACKEND": "apps.common.storage.CloudinaryMediaStorage"}
