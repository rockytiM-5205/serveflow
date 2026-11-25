"""Staff order endpoints, mounted under /restaurants/<slug>/ (tenant-scoped, role-checked)."""
from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from apps.audit.services import record
from apps.common.exceptions import Conflict
from apps.common.pagination import DefaultCursorPagination
from apps.common.schema import SLUG_PARAM, staff_schema
from apps.restaurants.models import MembershipRole
from apps.restaurants.permissions import ROLE_RANK, RestaurantScopedMixin

from . import idempotency
from .models import IdempotencyScope, LateFeeStatus, Order, OrderStatus, PaymentStatus
from .public_views import IDEMPOTENCY_PARAM
from .serializers import (
    BulkPaymentResultSerializer, BulkPaymentSerializer, BulkTransitionResultSerializer, BulkTransitionSerializer, CancelSerializer, PaymentSerializer, StaffOrderDetailSerializer, StaffOrderListSerializer, TransitionSerializer,
)
from .services import record_payment
from .workflow import actor_type_for, advance_to, change_status

STAFF = MembershipRole.STAFF
OPEN_STATUSES = [OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.SERVING, OrderStatus.READY_FOR_PICKUP]


class OrderPagination(DefaultCursorPagination):
    ordering = ("-created_at", "-id")


def load_detail(restaurant, public_id):
    return (
        Order.objects.filter(restaurant=restaurant, public_id=public_id)
        .prefetch_related("items", "payments__recorded_by", "events__actor_user")
        .get()
    )


FILTERS = [
    OpenApiParameter("status", str, description="Comma-separated statuses, e.g. PENDING,CONFIRMED"),
    OpenApiParameter("payment_status", str, description="UNPAID, CLAIMED (customer says paid) or PAID"),
    OpenApiParameter("fulfilment_type", str, description="PICKUP or DINE_IN"),
    OpenApiParameter("business_date", str, description="YYYY-MM-DD in the restaurant's timezone"),
    OpenApiParameter("code", int, description="Order code, e.g. 42 for #042"),
    OpenApiParameter("queue", int, description="1 = orders that still need attention: open, completed but unpaid, or with a late fee to collect"),
]


@staff_schema(extra_parameters=FILTERS, get="List orders, newest first")
class OrderListView(RestaurantScopedMixin, ListAPIView):
    min_role = STAFF
    queryset = Order.objects.prefetch_related("items")
    serializer_class = StaffOrderListSerializer
    pagination_class = OrderPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        if getattr(self, "swagger_fake_view", False):
            return queryset
        params = self.request.query_params
        statuses = [s for s in params.get("status", "").split(",") if s in OrderStatus.values]
        if statuses:
            queryset = queryset.filter(status__in=statuses)
        if params.get("payment_status") in PaymentStatus.values:
            queryset = queryset.filter(payment_status=params["payment_status"])
        if params.get("fulfilment_type") in ("PICKUP", "DINE_IN"):
            queryset = queryset.filter(fulfilment_type=params["fulfilment_type"])
        try:
            if params.get("business_date"):
                queryset = queryset.filter(business_date=date.fromisoformat(params["business_date"]))
        except ValueError:
            queryset = queryset.none()
        code = params.get("code", "")
        if code.isdigit() and len(code) <= 9:
            queryset = queryset.filter(order_number=int(code))
        search = params.get("search", "").strip()[:40]
        if search:
            match = Q(reference__iexact=search) | Q(customer_name__icontains=search) | Q(customer_phone__endswith=search)
            if len(search) >= 4:
                match |= Q(reference__iendswith=search)  # just the random end, e.g. 8K29P, is enough at the counter
            queryset = queryset.filter(match)
        if params.get("queue") == "1":
            queryset = queryset.filter(
                Q(status__in=OPEN_STATUSES) | Q(status=OrderStatus.COMPLETED, payment_status=PaymentStatus.UNPAID)
                | Q(late_fee_status=LateFeeStatus.DUE)
            )
        return queryset


@staff_schema(get="Order details, including the customer's phone number and the full history")
class OrderDetailView(RestaurantScopedMixin, RetrieveAPIView):
    min_role = STAFF
    queryset = Order.objects.prefetch_related("items", "payments__recorded_by", "events__actor_user")
    serializer_class = StaffOrderDetailSerializer
    lookup_field = "public_id"


class OrderActionView(RestaurantScopedMixin, GenericAPIView):
    """Base for actions on one order. The order is looked up inside the caller's restaurant only."""

    min_role = STAFF
    queryset = Order.objects.all()
    lookup_field = "public_id"
    http_method_names = ["post", "options"]

    def detail_response(self, order):
        return Response(StaffOrderDetailSerializer(load_detail(self.request.restaurant, order.public_id)).data)


class OrderTransitionView(OrderActionView):
    serializer_class = TransitionSerializer

    @extend_schema(
        parameters=[SLUG_PARAM], request=TransitionSerializer, responses=StaffOrderDetailSerializer,
        summary="Confirm, reject, start preparing, mark ready or mark completed (the billable step). Send expected_status to avoid acting on a stale view.",
    )
    def post(self, request, *args, **kwargs):
        order = self.get_object()
        serializer = TransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        change_status(
            order=order, to_status=data["to_status"], actor_type=actor_type_for(request.membership.role),
            actor_user=request.user, reason=data["reason"], expected_status=data.get("expected_status"),
        )
        return self.detail_response(order)


class OrderCancelView(OrderActionView):
    serializer_class = CancelSerializer

    @extend_schema(
        parameters=[SLUG_PARAM], request=CancelSerializer, responses=StaffOrderDetailSerializer,
        summary="Cancel an order with a reason. While it is being prepared or is ready this needs a manager or owner and acknowledge_serving.",
    )
    def post(self, request, *args, **kwargs):
        order = self.get_object()
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        change_status(
            order=order, to_status=OrderStatus.CANCELLED, actor_type=actor_type_for(request.membership.role),
            actor_user=request.user, reason=data["reason"], expected_status=data.get("expected_status"),
            acknowledge_serving=data["acknowledge_serving"],
        )
        return self.detail_response(order)


class OrderPaymentView(OrderActionView):
    serializer_class = PaymentSerializer

    @extend_schema(
        parameters=[SLUG_PARAM, IDEMPOTENCY_PARAM], request=PaymentSerializer, responses=StaffOrderDetailSerializer,
        summary="Confirm that the customer's payment arrived (cash or transfer). Required before preparing starts. One payment per order.",
    )
    def post(self, request, *args, **kwargs):
        order = self.get_object()
        key = idempotency.read_key(request)
        serializer = PaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        request_hash = idempotency.fingerprint({
            "order": str(order.public_id), "method": data["method"], "amount": str(data["amount"]),
            "reference": data["reference"],
        })
        restaurant = request.restaurant
        stored = idempotency.find_replay(restaurant, IdempotencyScope.PAYMENT_RECORD, key, request_hash)
        if stored:
            return idempotency.replay_response(stored)
        try:
            with transaction.atomic():
                record_payment(
                    order=order, actor_user=request.user, method=data["method"], amount=data["amount"],
                    reference=data["reference"],
                )
                body = StaffOrderDetailSerializer(load_detail(restaurant, order.public_id)).data
                idempotency.remember(restaurant, IdempotencyScope.PAYMENT_RECORD, key, request_hash, 200, body)
        except IntegrityError:
            stored = idempotency.find_replay(restaurant, IdempotencyScope.PAYMENT_RECORD, key, request_hash)
            if stored:
                return idempotency.replay_response(stored)
            raise
        return Response(body)


class OrderBulkPaymentView(RestaurantScopedMixin, GenericAPIView):
    """Confirm many payments at once, for a restaurant checking a busy stretch of bank alerts against its orders."""

    min_role = STAFF
    serializer_class = BulkPaymentSerializer

    @extend_schema(
        parameters=[SLUG_PARAM, IDEMPOTENCY_PARAM], request=BulkPaymentSerializer, responses=BulkPaymentResultSerializer,
        summary="Confirm the payment of up to 50 orders at once (each for its full total, with its reference as the bank reference). "
                "Orders that can't be confirmed are listed in `skipped`, the rest still go through. Header Idempotency-Key required.",
    )
    def post(self, request, *args, **kwargs):
        key = idempotency.read_key(request)
        serializer = BulkPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = sorted(set(serializer.validated_data["orders"]), key=str)
        method = serializer.validated_data["method"]
        restaurant = request.restaurant
        start = serializer.validated_data["start_preparing"]
        actor_type = actor_type_for(request.membership.role)
        request_hash = idempotency.fingerprint({"orders": [str(i) for i in ids], "method": method, "start_preparing": start})
        stored = idempotency.find_replay(restaurant, IdempotencyScope.PAYMENT_RECORD, key, request_hash)
        if stored:
            return idempotency.replay_response(stored)

        found = {o.public_id: o for o in Order.objects.filter(restaurant=restaurant, public_id__in=ids)}
        confirmed, skipped = [], []
        for public_id in ids:
            order = found.get(public_id)
            if order is None:
                skipped.append({"public_id": str(public_id), "reason": "not_found"})
                continue
            try:
                with transaction.atomic():  # one order failing never undoes the others
                    record_payment(order=order, actor_user=request.user, method=method, amount=order.total, reference=order.reference)
                    if start and order.status in (OrderStatus.PENDING, OrderStatus.CONFIRMED):
                        advance_to(order=order, to_status=OrderStatus.SERVING, actor_type=actor_type, actor_user=request.user)
                confirmed.append(str(public_id))
            except Conflict as exc:
                skipped.append({"public_id": str(public_id), "reference": order.reference, "reason": getattr(exc.detail, "code", "conflict")})
        body = {"confirmed": confirmed, "skipped": skipped}
        if confirmed:
            record(
                restaurant=restaurant, actor=request.user, action="payment.bulk_confirmed", entity_type="restaurant",
                entity_id=restaurant.pk, metadata={"count": len(confirmed), "method": method, "started_preparing": start},
            )
        try:
            with transaction.atomic():
                idempotency.remember(restaurant, IdempotencyScope.PAYMENT_RECORD, key, request_hash, 200, body)
        except IntegrityError:  # the same request arrived twice at once: answer with the first one's result
            stored = idempotency.find_replay(restaurant, IdempotencyScope.PAYMENT_RECORD, key, request_hash)
            if stored:
                return idempotency.replay_response(stored)
            raise
        return Response(body)


class OrderBulkTransitionView(RestaurantScopedMixin, GenericAPIView):
    """Move many orders forward in one go: accept, start preparing, mark ready or complete."""

    min_role = STAFF
    serializer_class = BulkTransitionSerializer

    @extend_schema(
        parameters=[SLUG_PARAM], request=BulkTransitionSerializer, responses=BulkTransitionResultSerializer,
        summary="Move up to 50 orders forward to `to_status`, passing through the steps in between (a pending order that is paid can go straight to "
                "preparing). Orders that can't move (not paid yet, already there, wrong state) are listed in `skipped`; the rest still go through.",
    )
    def post(self, request, *args, **kwargs):
        serializer = BulkTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = sorted(set(serializer.validated_data["orders"]), key=str)
        to_status = serializer.validated_data["to_status"]
        actor_type = actor_type_for(request.membership.role)
        found = {o.public_id: o for o in Order.objects.filter(restaurant=request.restaurant, public_id__in=ids)}
        moved, skipped = [], []
        for public_id in ids:
            order = found.get(public_id)
            if order is None:
                skipped.append({"public_id": str(public_id), "reason": "not_found"})
                continue
            try:
                advance_to(order=order, to_status=to_status, actor_type=actor_type, actor_user=request.user)
                moved.append(str(public_id))
            except Conflict as exc:
                skipped.append({"public_id": str(public_id), "reference": order.reference, "reason": getattr(exc.detail, "code", "conflict")})
        return Response({"moved": moved, "skipped": skipped})


class LateFeeActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["paid", "waive"])
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


@extend_schema_view(post=extend_schema(parameters=[SLUG_PARAM], request=LateFeeActionSerializer, responses=StaffOrderDetailSerializer,
                                       summary="Settle a late pickup fee: mark it collected, or waive it (manager or owner, with a reason)"))
class OrderLateFeeView(RestaurantScopedMixin, GenericAPIView):
    """A late fee is worked out when the order is completed. Staff collect it and mark it paid, or a manager waives it. Both are audited."""

    min_role = MembershipRole.STAFF
    serializer_class = LateFeeActionSerializer

    def post(self, request, slug, public_id):
        data = LateFeeActionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        action, reason = data.validated_data["action"], data.validated_data["reason"].strip()
        if action == "waive":
            if ROLE_RANK[request.membership.role] < ROLE_RANK[MembershipRole.MANAGER]:
                raise PermissionDenied("Only a manager or owner can waive a late fee.", code="insufficient_role")
            if len(reason) < 3:
                raise ValidationError({"reason": ["Say why the fee is waived."]})
        with transaction.atomic():
            order = get_object_or_404(Order.objects.select_for_update(), restaurant=request.restaurant, public_id=public_id)
            if order.late_fee_status != LateFeeStatus.DUE:
                raise Conflict("There is no late fee waiting on this order.", code="no_late_fee_due", details={"late_fee_status": order.late_fee_status})
            order.late_fee_status = LateFeeStatus.PAID if action == "paid" else LateFeeStatus.WAIVED
            order.save(update_fields=["late_fee_status", "updated_at"])
            record(restaurant=request.restaurant, actor=request.user, action=f"order.late_fee_{'paid' if action == 'paid' else 'waived'}",
                   entity_type="order", entity_id=order.pk, metadata={"code": order.code, "fee": str(order.late_fee), "reason": reason})
        return Response(StaffOrderDetailSerializer(order).data)
