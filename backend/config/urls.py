"""Root URL configuration."""
import re

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve
from apps.restaurants.views import RestaurantCreateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

handler404 = "apps.common.views.not_found"


def healthz(request):
    """Always answers 200 without touching the database. Used by the host's health check and uptime monitors."""
    return HttpResponse("ok", content_type="text/plain")


def media_urlpatterns():
    """Uploaded pictures under MEDIA_URL, served by Django. Only for development (SERVE_MEDIA_FILES, or DEBUG): in production the
    web server serves MEDIA_ROOT. Django's own `static()` helper returns nothing unless DEBUG is on, which is why pictures
    were saved but never shown when DEBUG was off."""
    if not (settings.DEBUG or getattr(settings, "SERVE_MEDIA_FILES", False)):
        return []
    prefix = re.escape(settings.MEDIA_URL.lstrip("/"))
    return [re_path(rf"^{prefix}(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]


urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/platform/", include("apps.platform_admin.urls")),
    path("api/v1/restaurants/", RestaurantCreateView.as_view(), name="restaurant-create"),
    # Public (customer) routes first, then staff routes; both live under one slug prefix.
    path("api/v1/restaurants/<slug:slug>/", include("apps.restaurants.public_urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.menu.public_urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.orders.public_urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.reviews.public_urls")),
    path("api/v1/marketplace/", include("apps.marketplace.urls")),
    path("api/v1/customers/", include("apps.customers.urls")),
    path("api/v1/orders/", include("apps.orders.token_urls")),
    path("api/v1/orders/", include("apps.reviews.token_urls")),
    path("api/v1/billing/", include("apps.platform_admin.public_urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.restaurants.urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.menu.urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.audit.urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.orders.urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.reviews.urls")),
    path("api/v1/restaurants/<slug:slug>/", include("apps.platform_admin.billing_urls")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

urlpatterns += media_urlpatterns()
