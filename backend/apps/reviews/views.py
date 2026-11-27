from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from apps.common.throttles import ScopedRateThrottle
from rest_framework.views import APIView

from apps.common.authentication import CsrfSessionAuthentication
from apps.common.pagination import DefaultCursorPagination
from apps.customers.permissions import IsCustomer
from apps.common.schema import SLUG_PARAM
from apps.orders.public_views import PRIVATE_HEADERS, TOKEN_PARAM, load_order
from apps.orders.serializers import PublicOrderSerializer
from apps.platform_admin.views import OwnerMixin, _search, hidden
from apps.restaurants.models import MembershipRole, Restaurant
from apps.restaurants.permissions import RestaurantScopedMixin

from . import services
from .models import Review, ReviewReport

PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX = 10, 50


class ReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class PublicReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ("rating", "comment", "display_name", "created_at")
        read_only_fields = fields


class PublicReviewListSerializer(serializers.Serializer):
    average = serializers.FloatField(allow_null=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    has_next = serializers.BooleanField()
    results = PublicReviewSerializer(many=True)


class PageParams(serializers.Serializer):
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=PAGE_SIZE_MAX, default=PAGE_SIZE_DEFAULT)


# ---------------------------------------------------------------- customers (no account: the order's private link is the proof)
class OrderReviewView(APIView):
    """Review an order you placed, once it is completed. You must be signed in to a customer account, and you can review each restaurant once.
    Holding the order's private link proves the order was yours."""

    authentication_classes = [CsrfSessionAuthentication]
    permission_classes = [IsCustomer]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "order_cancel"

    @extend_schema(parameters=[TOKEN_PARAM], request=ReviewCreateSerializer, responses=PublicOrderSerializer, summary="Review a completed order (once)")
    def post(self, request, token):
        order = load_order(token)
        data = ReviewCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.create_review(order.pk, data.validated_data["rating"], data.validated_data["comment"], request.user.customer_profile)
        return Response(PublicOrderSerializer(load_order(token), context={"request": request}).data, status=201, headers=PRIVATE_HEADERS)


class PublicReviewListView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "marketplace"

    @extend_schema(parameters=[SLUG_PARAM, PageParams], responses=PublicReviewListSerializer, summary="A restaurant's published reviews, newest first")
    def get(self, request, slug):
        restaurant = get_object_or_404(Restaurant, slug=slug, is_active=True)
        params = PageParams(data=request.query_params)
        params.is_valid(raise_exception=True)
        size, page = params.validated_data["page_size"], params.validated_data["page"]
        qs = Review.objects.filter(restaurant=restaurant, status=Review.Status.PUBLISHED)
        total = qs.count()
        rows = list(qs[(page - 1) * size: page * size])
        return Response({
            "average": float(restaurant.rating_average) if restaurant.rating_average is not None else None, "count": restaurant.rating_count,
            "page": page, "page_size": size, "has_next": page * size < total, "results": PublicReviewSerializer(rows, many=True).data,
        })


# ---------------------------------------------------------------- the restaurant: read and report, never edit
class StaffReviewSerializer(serializers.ModelSerializer):
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    open_reports = serializers.IntegerField(read_only=True)

    class Meta:
        model = Review
        fields = ("id", "rating", "comment", "display_name", "status", "order_reference", "open_reports", "created_at")
        read_only_fields = fields


class ReportCreateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


@extend_schema_view(get=extend_schema(parameters=[SLUG_PARAM], summary="Your restaurant's reviews, with any you have reported"))
class ReviewInboxView(RestaurantScopedMixin, ListAPIView):
    min_role = MembershipRole.STAFF
    serializer_class = StaffReviewSerializer
    pagination_class = DefaultCursorPagination

    def get_queryset(self):
        return (Review.objects.filter(restaurant=self.request.restaurant).select_related("order")
                .annotate(open_reports=Count("reports", filter=Q(reports__status=ReviewReport.Status.OPEN))).order_by("-id"))


@extend_schema_view(post=extend_schema(parameters=[SLUG_PARAM], request=ReportCreateSerializer, responses={204: None}, summary="Ask the platform to look at a review (manager or owner)"))
class ReviewReportView(RestaurantScopedMixin, GenericAPIView):
    min_role = MembershipRole.MANAGER
    serializer_class = ReportCreateSerializer

    def post(self, request, slug, pk):
        data = ReportCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.report_review(request.restaurant, pk, request.user, data.validated_data["reason"])
        return Response(status=204)


# ---------------------------------------------------------------- the platform owner
class OwnerReviewSerializer(serializers.BaseSerializer):
    def to_representation(self, r):
        open_reports = [x for x in r.reports.all() if x.status == ReviewReport.Status.OPEN]
        return {
            "id": r.pk, "restaurant_name": r.restaurant.name, "restaurant_slug": r.restaurant.slug, "rating": r.rating, "comment": r.comment,
            "display_name": r.display_name, "status": r.status, "moderation_reason": r.moderation_reason, "created_at": r.created_at,
            "open_reports": [{"reason": x.reason, "reported_at": x.created_at} for x in open_reports],
        }


@hidden("get")
class OwnerReviewListView(OwnerMixin, ListAPIView):
    serializer_class = OwnerReviewSerializer
    pagination_class = DefaultCursorPagination

    def get_queryset(self):
        qs = Review.objects.select_related("restaurant").prefetch_related("reports")
        qs = _search(qs, self.request, "restaurant__name", "comment", "display_name")
        status = self.request.query_params.get("status", "").strip().upper()
        if status:
            if status not in Review.Status.values:
                raise serializers.ValidationError({"status": ["Use PUBLISHED or HIDDEN."]})
            qs = qs.filter(status=status)
        if self.request.query_params.get("reported") == "1":
            qs = qs.filter(reports__status=ReviewReport.Status.OPEN).distinct()
        return qs.order_by("-id")


@hidden("post")
class OwnerReviewHideView(OwnerMixin, APIView):
    def post(self, request, pk):
        data = request.data if isinstance(request.data, dict) else {}
        services.hide_review(pk, request.user, str(data.get("reason", "")))
        return Response(status=204)


@hidden("post")
class OwnerReviewRestoreView(OwnerMixin, APIView):
    def post(self, request, pk):
        services.restore_review(pk, request.user)
        return Response(status=204)


@hidden("post")
class OwnerReviewDismissView(OwnerMixin, APIView):
    def post(self, request, pk):
        services.dismiss_reports(pk, request.user)
        return Response(status=204)
