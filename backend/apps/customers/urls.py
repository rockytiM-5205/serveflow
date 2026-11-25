"""Customer accounts under /api/v1/customers/. Every route except register and login needs a signed-in customer account."""
from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.RegisterView.as_view(), name="customer-register"),
    path("login/", views.LoginView.as_view(), name="customer-login"),
    path("logout/", views.LogoutView.as_view(), name="customer-logout"),
    path("me/", views.MeView.as_view(), name="customer-me"),
    path("password/", views.PasswordView.as_view(), name="customer-password"),
    path("orders/", views.OrderListView.as_view(), name="customer-orders"),
    path("orders/claim/", views.ClaimView.as_view(), name="customer-order-claim"),
    path("orders/<uuid:public_id>/", views.OrderDetailView.as_view(), name="customer-order"),
]
