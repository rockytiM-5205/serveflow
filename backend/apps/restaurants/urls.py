"""Staff routes, mounted at /api/v1/restaurants/<slug>/. Every view here must inherit
RestaurantScopedMixin (a test enforces it)."""
from django.urls import path

from . import push_views, views

urlpatterns = [
    path("members/", views.MemberListView.as_view(), name="restaurant-members"),
    path("members/<int:pk>/", views.MemberDetailView.as_view(), name="restaurant-member"),
    path("settings/", views.RestaurantSettingsView.as_view(), name="restaurant-settings"),
    path("hours/", views.HoursView.as_view(), name="restaurant-hours"),
    path("payment-account/", views.PaymentAccountView.as_view(), name="restaurant-payment-account"),
    path("push/config/", push_views.PushConfigView.as_view(), name="restaurant-push-config"),
    path("push/subscribe/", push_views.PushSubscribeView.as_view(), name="restaurant-push-subscribe"),
    path("push/unsubscribe/", push_views.PushUnsubscribeView.as_view(), name="restaurant-push-unsubscribe"),
    path("push/test/", push_views.PushTestView.as_view(), name="restaurant-push-test"),
    path("images/logo/", views.RestaurantPictureView.as_view(kind="logo"), name="restaurant-logo"),
    path("images/cover/", views.RestaurantPictureView.as_view(kind="cover"), name="restaurant-cover"),
]
