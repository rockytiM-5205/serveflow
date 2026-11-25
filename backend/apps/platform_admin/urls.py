"""Owner routes under /api/v1/platform/ (see docs/owner-api-contract.md)."""
from django.urls import path

from apps.reviews import views as review_views

from . import views

urlpatterns = [
    path("me/", views.MeView.as_view(), name="platform-me"),
    path("overview/", views.OverviewView.as_view(), name="platform-overview"),
    path("usage/", views.UsageView.as_view(), name="platform-usage"),
    path("customers/", views.CustomerListCreateView.as_view(), name="platform-customers"),
    path("customers/<int:pk>/", views.CustomerDetailView.as_view(), name="platform-customer"),
    path("customers/<int:pk>/reset-admin-password/", views.CustomerResetAdminPasswordView.as_view(), name="platform-customer-reset-admin"),
    path("customers/<int:pk>/extend/", views.CustomerExtendView.as_view(), name="platform-customer-extend"),
    path("customers/<int:pk>/plan/", views.CustomerPlanView.as_view(), name="platform-customer-plan"),
    path("customers/<int:pk>/grant-orders/", views.CustomerGrantOrdersView.as_view(), name="platform-customer-grant-orders"),
    path("customers/<int:pk>/suspend/", views.CustomerSuspendView.as_view(), name="platform-customer-suspend"),
    path("customers/<int:pk>/reactivate/", views.CustomerReactivateView.as_view(), name="platform-customer-reactivate"),
    path("credentials/", views.CredentialListCreateView.as_view(), name="platform-credentials"),
    path("credentials/<int:pk>/revoke/", views.CredentialRevokeView.as_view(), name="platform-credential-revoke"),
    path("plans/", views.PlanListCreateView.as_view(), name="platform-plans"),
    path("plans/<int:pk>/", views.PlanUpdateView.as_view(), name="platform-plan"),
    path("plans/<int:pk>/archive/", views.PlanArchiveView.as_view(), name="platform-plan-archive"),
    path("subscriptions/", views.SubscriptionListView.as_view(), name="platform-subscriptions"),
    path("payments/", views.PaymentListView.as_view(), name="platform-payments"),
    path("payments/<int:pk>/confirm/", views.PaymentConfirmView.as_view(), name="platform-payment-confirm"),
    path("payments/<int:pk>/fail/", views.PaymentFailView.as_view(), name="platform-payment-fail"),
    path("reviews/", review_views.OwnerReviewListView.as_view(), name="platform-reviews"),
    path("reviews/<int:pk>/hide/", review_views.OwnerReviewHideView.as_view(), name="platform-review-hide"),
    path("reviews/<int:pk>/restore/", review_views.OwnerReviewRestoreView.as_view(), name="platform-review-restore"),
    path("reviews/<int:pk>/dismiss/", review_views.OwnerReviewDismissView.as_view(), name="platform-review-dismiss"),
    path("audit/", views.AuditListView.as_view(), name="platform-audit"),
    path("notifications/", views.NotificationSummaryView.as_view(), name="platform-notifications"),
    path("notifications/read/", views.NotificationReadView.as_view(), name="platform-notifications-read"),
    path("settings/", views.SettingsView.as_view(), name="platform-settings"),
]
