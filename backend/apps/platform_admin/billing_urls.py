"""Restaurant-owner billing routes, mounted at /api/v1/restaurants/<slug>/. Names start with "billing-" so the subscription
lock (middleware.py) lets a locked restaurant reach them: it has to be able to pay. Every view uses RestaurantScopedMixin."""
from django.urls import path

from . import billing_views as views

urlpatterns = [
    path("billing/", views.BillingView.as_view(), name="billing-overview"),
    path("billing/subscribe/", views.SubscribeView.as_view(), name="billing-subscribe"),
    path("billing/payments/", views.ReportPaymentView.as_view(), name="billing-report-payment"),
    path("billing/order-packs/", views.OrderPackPurchaseView.as_view(), name="billing-order-packs"),
    path("billing/plan-change/cancel/", views.PlanChangeCancelView.as_view(), name="billing-plan-change-cancel"),
]
