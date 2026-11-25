"""Public: a restaurant's published reviews. Mounted at /api/v1/restaurants/<slug>/."""
from django.urls import path

from . import views

urlpatterns = [path("reviews/", views.PublicReviewListView.as_view(), name="public-reviews")]
