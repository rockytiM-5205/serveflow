"""Customer routes under /api/v1/restaurants/<slug>/. No authentication."""
from django.urls import path

from . import public_views

urlpatterns = [
    path("checkout/", public_views.OrderCreateView.as_view(), name="public-order-create"),
    path("pickup-slots/", public_views.PickupSlotsView.as_view(), name="public-pickup-slots"),
]
