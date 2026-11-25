"""Public marketplace routes under /api/v1/marketplace/. A restaurant's own page is /api/v1/restaurants/<slug>/ (profile) and
/api/v1/restaurants/<slug>/menu/ (menu): the marketplace and the restaurant's own link use the same data and the same ordering."""
from django.urls import path

from . import views

urlpatterns = [
    path("restaurants/", views.RestaurantSearchView.as_view(), name="marketplace-restaurants"),
    path("categories/", views.CategoryListView.as_view(), name="marketplace-categories"),
    path("areas/", views.AreaListView.as_view(), name="marketplace-areas"),
]
