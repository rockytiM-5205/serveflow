"""A restaurant's own web app manifest, so a customer's "Add to Home Screen" installs that restaurant (its name, its logo, its page)
instead of the generic ServeFlow app. Public, like the restaurant's page. Served at /api/v1/restaurants/<slug>/manifest.webmanifest."""
from django.http import Http404, JsonResponse
from django.views import View

from apps.common.images import media_url

from .models import Restaurant

CUSTOMER_APP = "/customer/"
DEFAULT_ICONS = [
    {"src": "/shared/assets/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
    {"src": "/shared/assets/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    {"src": "/shared/assets/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
]


def build_manifest(restaurant):
    start = f"{CUSTOMER_APP}index.html?r={restaurant.slug}"
    icons = list(DEFAULT_ICONS)
    logo = media_url(restaurant.logo) or ""
    if logo.startswith(("/", "https://")):  # the restaurant's own uploaded logo goes first; the standard icons stay as the fallback
        icons.insert(0, {"src": logo, "sizes": "512x512", "type": "image/webp", "purpose": "any"})
    return {
        "id": start,
        "name": restaurant.name,
        "short_name": restaurant.name[:12],
        "description": f"Order from {restaurant.name}.",
        "start_url": start,
        "scope": CUSTOMER_APP,
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#073a2b",
        "icons": icons,
    }


class RestaurantManifestView(View):
    """Not part of the JSON API: browsers read it, so it has its own content type. Suspended restaurants look like they don't exist."""

    def get(self, request, slug):
        restaurant = Restaurant.objects.filter(slug=slug, is_active=True).first()
        if restaurant is None:
            raise Http404
        response = JsonResponse(build_manifest(restaurant), content_type="application/manifest+json")
        response["Cache-Control"] = "public, max-age=3600"
        return response
