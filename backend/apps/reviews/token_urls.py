"""Customer route under /api/v1/orders/: reviewing a completed order. The token in the path is the credential."""
from django.urls import path

from . import views

urlpatterns = [path("<str:token>/review/", views.OrderReviewView.as_view(), name="public-order-review")]
