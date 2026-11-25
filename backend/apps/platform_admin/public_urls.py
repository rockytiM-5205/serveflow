"""Public billing routes under /api/v1/billing/ (no sign-in)."""
from django.urls import path

from . import billing_views as views

urlpatterns = [
    path("plans/", views.PublicPlansView.as_view(), name="billing-public-plans"),
    path("webhooks/<str:provider>/", views.PaymentWebhookView.as_view(), name="billing-webhook"),
]
