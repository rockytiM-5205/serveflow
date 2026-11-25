"""Staff routes, mounted at /api/v1/restaurants/<slug>/. Every view here inherits RestaurantScopedMixin."""
from django.urls import path

from . import views

urlpatterns = [
    path("reviews/inbox/", views.ReviewInboxView.as_view(), name="staff-reviews"),
    path("reviews/<int:pk>/report/", views.ReviewReportView.as_view(), name="staff-review-report"),
]
