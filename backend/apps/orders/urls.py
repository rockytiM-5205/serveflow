"""Staff routes under /api/v1/restaurants/<slug>/ (must all use RestaurantScopedMixin)."""
from django.urls import path

from . import views

urlpatterns = [
    path("orders/", views.OrderListView.as_view(), name="staff-orders"),
    path("orders/transitions/", views.OrderBulkTransitionView.as_view(), name="staff-orders-transitions"),
    path("orders/payments/confirm/", views.OrderBulkPaymentView.as_view(), name="staff-orders-confirm-payments"),
    path("orders/<uuid:public_id>/", views.OrderDetailView.as_view(), name="staff-order"),
    path("orders/<uuid:public_id>/transitions/", views.OrderTransitionView.as_view(), name="staff-order-transition"),
    path("orders/<uuid:public_id>/cancel/", views.OrderCancelView.as_view(), name="staff-order-cancel"),
    path("orders/<uuid:public_id>/payment/", views.OrderPaymentView.as_view(), name="staff-order-payment"),
    path("orders/<uuid:public_id>/late-fee/", views.OrderLateFeeView.as_view(), name="staff-order-late-fee"),
]
