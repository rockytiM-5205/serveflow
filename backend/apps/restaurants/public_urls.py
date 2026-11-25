"""Public routes under /api/v1/restaurants/<slug>/. No authentication."""
from django.urls import path

from . import manifest, views

urlpatterns = [
    path("", views.PublicRestaurantView.as_view(), name="public-restaurant"),
    path("manifest.webmanifest", manifest.RestaurantManifestView.as_view(), name="restaurant-manifest"),
]
