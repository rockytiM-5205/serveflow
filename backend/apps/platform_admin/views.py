"""Owner API under /api/v1/platform/. Every view requires IsPlatformOwner. These routes are deliberately left out
of the public OpenAPI schema (they are private to ServeFlow)."""
from datetime import date, timedelta

from django.db import transaction
from django.db.models import BigIntegerField, Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.generics import ListAPIView, ListCreateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import UserSerializer
from apps.common.exceptions import Conflict
from apps.common.pagination import DefaultCursorPagination
from apps.restaurants.models import MembershipRole, Restaurant, RestaurantMembership

from . import customers, notifications, reports, services
from .models import (
    ApiCredential, ApiUsageDaily, BillingPeriod, OrderPack, OrderUsage, PaymentDetails, Plan, PlatformAuditEvent, Subscription,
    SubscriptionPayment,
)
from .permissions import IsPlatformOwner
from .serializers import (
    AdminUpdateSerializer, AuditRowSerializer, CredentialCreateSerializer, CredentialSerializer, CustomerSerializer,
    OwnerRestaurantCreateSerializer, OwnerRestaurantUpdateSerializer, PaymentRowSerializer,
    PaymentDetailsSerializer, PlanSerializer, SubscriptionRowSerializer, credential_row,
)


def hidden(*methods):
    return extend_schema_view(**{m: extend_schema(exclude=True) for m in methods})


class OwnerMixin:
    permission_classes = [IsPlatformOwner]


class AuditPagination(DefaultCursorPagination):
    ordering = ("-created_at", "-id")


def _search(queryset, request, *fields):
    term = request.query_params.get("search", "").strip()[:100]
    if not term:
        return queryset
    query = Q()
    for field in fields:
        query |= Q(**{f"{field}__icontains": term})
    return queryset.filter(query)


def _choice(request, name, allowed):
    value = request.query_params.get(name, "").strip().upper()
    if not value:
        return None
    if value not in allowed:
        raise serializers.ValidationError({name: [f"Use one of: {', '.join(sorted(allowed))}."]})
    return value


@hidden("get")
class MeView(OwnerMixin, APIView):
    def get(self, request):
        return Response({"user": UserSerializer(request.user).data})


@hidden("get")
class OverviewView(OwnerMixin, APIView):
    RANGES = {"7d": 7, "30d": 30, "90d": 90}

    def get(self, request):
        key = request.query_params.get("range", "30d")
        if key not in self.RANGES:
            raise serializers.ValidationError({"range": ["Use 7d, 30d or 90d."]})
        return Response(reports.overview_report(self.RANGES[key]))


@hidden("get")
class UsageView(OwnerMixin, APIView):
    def get(self, request):
        today = timezone.localdate()
        try:
            end = date.fromisoformat(request.query_params.get("to", today.isoformat()))
            start = date.fromisoformat(request.query_params.get("from", (end - timedelta(days=29)).isoformat()))
        except ValueError:
            raise serializers.ValidationError({"from": ["Use dates like 2026-10-01."]}) from None
        if start > end:
            raise serializers.ValidationError({"from": ["The start date must be on or before the end date."]})
        if (end - start).days > 365:
            raise serializers.ValidationError({"from": ["Choose a range of at most 366 days."]})
        return Response(reports.usage_report(start, end))


# ---------- customers (restaurant accounts) ----------
def _customers():
    since = timezone.localdate() - timedelta(days=29)
    usage = ApiUsageDaily.objects.filter(restaurant=OuterRef("pk"), date__gte=since).values("restaurant").annotate(t=Sum("requests")).values("t")
    admin = RestaurantMembership.objects.filter(restaurant=OuterRef("pk"), role=MembershipRole.OWNER, is_active=True).order_by("id").values("user__email")[:1]
    return Restaurant.objects.select_related("subscription__plan").annotate(
        requests_30d=Coalesce(Subquery(usage, output_field=BigIntegerField()), 0), admin_email=Subquery(admin))


RESTAURANT_FIELDS = ("description", "contact_phone", "address", "currency", "timezone", "pickup_enabled", "dine_in_enabled", "requires_table_number", "accepting_orders")


def customer_detail(restaurant_id):
    r = get_object_or_404(_customers(), pk=restaurant_id)
    data = CustomerSerializer(r).data
    sub = getattr(r, "subscription", None)
    admin = customers.admin_of(r)
    data.update({
        **{field: getattr(r, field) for field in RESTAURANT_FIELDS},
        "admin": {"id": admin.pk, "email": admin.email, "first_name": admin.first_name, "last_name": admin.last_name} if admin else None,
        "contact": {"email": admin.email if admin else None},
        "subscription": {"status": sub.status, "plan": {"id": sub.plan_id, "name": sub.plan.name, "is_trial": sub.plan.is_trial}, "next_plan": {"id": sub.next_plan_id, "name": sub.next_plan.name} if sub.next_plan_id else None, "current_period_start": sub.current_period_start,
                         "current_period_end": sub.current_period_end, "trial_ends_at": sub.trial_ends_at} if sub else None,
        "usage": reports.customer_usage(r.pk),
        "billing": reports.customer_billing(sub),
        "credentials": [credential_row(c) for c in ApiCredential.objects.select_related("restaurant__subscription__plan").filter(restaurant=r).order_by("-id")[:20]],
        "activity": [{"occurred_at": e.created_at, "summary": f"{e.action}: {e.summary}".strip(": ")}
                     for e in PlatformAuditEvent.objects.filter(resource_type="restaurant", resource_id=str(r.pk)).order_by("-created_at", "-id")[:10]],
        "allowed_actions": ["suspend" if r.is_active else "reactivate", "extend", "change_plan", "grant_orders", "reset_admin_password", "edit", "delete"],
    })
    return data


@hidden("get", "post")
class CustomerListCreateView(OwnerMixin, ListCreateAPIView):
    serializer_class = CustomerSerializer
    pagination_class = DefaultCursorPagination

    def get_queryset(self):
        qs, request = _customers(), self.request
        qs = _search(qs, request, "name", "slug", "admin_email")
        status = _choice(request, "status", {"ACTIVE", "SUSPENDED"})
        if status:
            qs = qs.filter(is_active=(status == "ACTIVE"))
        sub_status = _choice(request, "subscription_status", set(Subscription.Status.values))
        if sub_status:
            qs = qs.filter(subscription__status=sub_status)
        plan = request.query_params.get("plan", "").strip()
        if plan:
            if not plan.isdigit():
                raise serializers.ValidationError({"plan": ["Use a plan id."]})
            qs = qs.filter(subscription__plan_id=int(plan))
        return qs

    def create(self, request, *args, **kwargs):
        body = OwnerRestaurantCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        admin = {"email": data.pop("admin_email"), "first_name": data.pop("admin_first_name", ""),
                 "last_name": data.pop("admin_last_name", ""), "password": data.pop("admin_password", "")}
        plan, start = data.pop("plan_id", None), data.pop("start_trial", True)
        restaurant, user, temporary, subscription = customers.create_customer(actor=request.user, data=data, admin=admin, plan=plan, start_trial_now=start)
        # The temporary password is in this response only. Responses must never be cached.
        return Response({"customer": customer_detail(restaurant.pk), "admin_email": user.email, "temporary_password": temporary,
                         "trial_started": subscription is not None}, status=201, headers={"Cache-Control": "no-store"})


@hidden("get", "patch", "delete")
class CustomerDetailView(OwnerMixin, APIView):
    def get(self, request, pk):
        return Response(customer_detail(pk))

    def patch(self, request, pk):
        restaurant = get_object_or_404(Restaurant, pk=pk)
        body = request.data if isinstance(request.data, dict) else {}
        admin_data = body.get("admin")
        with transaction.atomic():
            serializer = OwnerRestaurantUpdateSerializer(restaurant, data={k: v for k, v in body.items() if k != "admin"}, partial=True)
            serializer.is_valid(raise_exception=True)
            admin_serializer = AdminUpdateSerializer(data=admin_data or {}, partial=True)
            admin_serializer.is_valid(raise_exception=True)
            serializer.save()
            if admin_data:
                customers.update_customer_admin(restaurant, request.user, admin_serializer.validated_data)
            services.audit(request.user, "customer.updated", "restaurant", restaurant.pk, restaurant.slug)
        return Response(customer_detail(pk))

    def delete(self, request, pk):
        customers.delete_customer(pk, request.user)
        return Response(status=204)


class _CustomerAction(OwnerMixin, APIView):
    active = False

    def post(self, request, pk):
        services.set_restaurant_active(pk, self.active, request.user)
        return Response(status=204)


@hidden("post")
class CustomerSuspendView(_CustomerAction):
    active = False


@hidden("post")
class CustomerReactivateView(_CustomerAction):
    active = True


@hidden("post")
class CustomerResetAdminPasswordView(OwnerMixin, APIView):
    def post(self, request, pk):
        password = customers.reset_admin_password(get_object_or_404(Restaurant, pk=pk), request.user)
        return Response({"temporary_password": password}, headers={"Cache-Control": "no-store"})


@hidden("post")
class CustomerExtendView(OwnerMixin, APIView):
    def post(self, request, pk):
        data = request.data if isinstance(request.data, dict) else {}
        days = data.get("days")
        if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 365:
            raise serializers.ValidationError({"days": ["Enter a whole number of days from 1 to 365."]})
        customers.extend_access(pk, request.user, days, str(data.get("reason", ""))[:120])
        return Response(customer_detail(pk))


@hidden("post")
class CustomerGrantOrdersView(OwnerMixin, APIView):
    """Add free order capacity to the running period. A reason is required and is recorded with the actor."""

    def post(self, request, pk):
        data = request.data if isinstance(request.data, dict) else {}
        customers.grant_orders(pk, request.user, data.get("orders"), str(data.get("reason", "")))
        return Response(customer_detail(pk))


@hidden("post")
class CustomerPlanView(OwnerMixin, APIView):
    def post(self, request, pk):
        data = request.data if isinstance(request.data, dict) else {}
        plan = Plan.objects.filter(pk=data.get("plan_id")).first() if isinstance(data.get("plan_id"), int) else None
        if plan is None:
            raise serializers.ValidationError({"plan_id": ["Choose a plan."]})
        customers.change_plan(pk, request.user, plan)
        return Response(customer_detail(pk))


# ---------- credentials ----------
@hidden("get", "post")
class CredentialListCreateView(OwnerMixin, ListCreateAPIView):
    serializer_class = CredentialSerializer
    pagination_class = DefaultCursorPagination

    def get_queryset(self):
        qs = ApiCredential.objects.select_related("restaurant__subscription__plan")
        qs = _search(qs, self.request, "name", "prefix", "restaurant__name", "restaurant__slug")
        status = _choice(self.request, "status", set(ApiCredential.Status.values))
        if status:
            qs = qs.filter(status=status)
        env = self.request.query_params.get("environment", "").strip().lower()
        if env:
            if env not in ApiCredential.Environment.values:
                raise serializers.ValidationError({"environment": ["Use live or test."]})
            qs = qs.filter(environment=env)
        return qs

    def create(self, request, *args, **kwargs):
        data = CredentialCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        credential, secret = services.create_credential(actor=request.user, **data.validated_data)
        # The secret appears in this response only. Responses must never be cached.
        return Response({"credential": credential_row(credential), "secret": secret}, status=201, headers={"Cache-Control": "no-store"})


@hidden("post")
class CredentialRevokeView(OwnerMixin, APIView):
    def post(self, request, pk):
        services.revoke_credential(pk, request.user)
        return Response(status=204)


# ---------- plans ----------
@hidden("get", "post")
class PlanListCreateView(OwnerMixin, ListCreateAPIView):
    serializer_class = PlanSerializer
    pagination_class = DefaultCursorPagination
    queryset = Plan.objects.all()

    def perform_create(self, serializer):
        with transaction.atomic():
            plan = serializer.save()
            services.audit(self.request.user, "plan.created", "plan", plan.pk, plan.name)


@hidden("patch")
class PlanUpdateView(OwnerMixin, APIView):
    def patch(self, request, pk):
        with transaction.atomic():
            plan = get_object_or_404(Plan.objects.select_for_update(), pk=pk)
            if plan.status == Plan.Status.ARCHIVED:
                raise Conflict("An archived plan can't be edited.", code="plan_archived")
            if plan.is_trial and set(request.data) - {"description", "included_orders", "included_requests", "rate_limit_per_minute", "features"}:
                raise serializers.ValidationError({"detail": ["The free trial plan is free and built in. You can change its description, request allowance, rate limit and features."]})
            serializer = PlanSerializer(plan, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            plan = serializer.save()
            services.audit(request.user, "plan.updated", "plan", plan.pk, plan.name)
        return Response(PlanSerializer(plan).data)


@hidden("post")
class PlanArchiveView(OwnerMixin, APIView):
    def post(self, request, pk):
        services.archive_plan(pk, request.user)
        return Response(status=204)


# ---------- subscriptions, payments, audit, settings ----------
@hidden("get")
class SubscriptionListView(OwnerMixin, ListAPIView):
    serializer_class = SubscriptionRowSerializer
    pagination_class = DefaultCursorPagination

    def get_queryset(self):
        latest = SubscriptionPayment.objects.filter(subscription=OuterRef("pk"), kind=SubscriptionPayment.Kind.SUBSCRIPTION).order_by("-transacted_at", "-id").values("status")[:1]
        period = BillingPeriod.objects.filter(subscription=OuterRef("pk"), starts_at__lte=timezone.now()).order_by("-starts_at")
        used = OrderUsage.objects.filter(billing_period=OuterRef("period_id")).values("billing_period").annotate(n=Count("id")).values("n")[:1]
        extra = OrderPack.objects.filter(billing_period=OuterRef("period_id"), status=OrderPack.Status.ACTIVE).values("billing_period").annotate(n=Sum("orders")).values("n")[:1]
        qs = (Subscription.objects.select_related("restaurant", "plan", "next_plan", "pending_plan")
              .annotate(payment_status=Subquery(latest), period_id=Subquery(period.values("id")[:1]), period_included=Subquery(period.values("included_orders")[:1]))
              .annotate(period_used=Subquery(used), period_extra=Subquery(extra)))
        qs = _search(qs, self.request, "restaurant__name", "restaurant__slug")
        status = _choice(self.request, "status", set(Subscription.Status.values))
        return qs.filter(status=status) if status else qs


@hidden("get")
class PaymentListView(OwnerMixin, ListAPIView):
    serializer_class = PaymentRowSerializer
    pagination_class = DefaultCursorPagination

    def get_queryset(self):
        qs = SubscriptionPayment.objects.select_related("subscription__restaurant")
        qs = _search(qs, self.request, "reference", "subscription__restaurant__name")
        status = _choice(self.request, "status", set(SubscriptionPayment.Status.values))
        kind = _choice(self.request, "kind", set(SubscriptionPayment.Kind.values))
        qs = qs.filter(kind=kind) if kind else qs
        return qs.filter(status=status) if status else qs


@hidden("post")
class PaymentConfirmView(OwnerMixin, APIView):
    def post(self, request, pk):
        services.confirm_payment(pk, request.user)
        return Response(status=204)


@hidden("post")
class PaymentFailView(OwnerMixin, APIView):
    """Mark a pending payment as failed. A reason is required and is audited with the actor."""

    def post(self, request, pk):
        data = request.data if isinstance(request.data, dict) else {}
        services.fail_payment(pk, request.user, str(data.get("reason", "")))
        return Response(status=204)


@hidden("get")
class AuditListView(OwnerMixin, ListAPIView):
    serializer_class = AuditRowSerializer
    pagination_class = AuditPagination

    def get_queryset(self):
        return _search(PlatformAuditEvent.objects.select_related("actor"), self.request, "actor__email", "action", "resource_type", "summary")


@hidden("get", "patch")
class SettingsView(OwnerMixin, APIView):
    def _payload(self):
        details = PaymentDetails.objects.first() or PaymentDetails()
        return {
            "platform": {"name": "ServeFlow", "currency": "NGN", "trial_days": services.trial_days(), "grace_days": services.grace_days()},
            "api_defaults": {},
            "payment_details": PaymentDetailsSerializer(details).data,
        }

    def get(self, request):
        return Response(self._payload())

    def patch(self, request):
        with transaction.atomic():
            details = PaymentDetails.objects.select_for_update().first() or PaymentDetails()
            serializer = PaymentDetailsSerializer(details, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            services.audit(request.user, "settings.payment_details_updated", "settings", "payment_details", "Payment details changed")
        return Response(self._payload())


@hidden("get")
class NotificationSummaryView(OwnerMixin, APIView):
    """The bell: the unread count and the latest notifications. Cheap enough to poll once a minute."""

    def get(self, request):
        return Response(notifications.summary())


@hidden("post")
class NotificationReadView(OwnerMixin, APIView):
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        ids = data.get("ids")
        if ids is not None and not (isinstance(ids, list) and all(isinstance(i, int) and not isinstance(i, bool) for i in ids) and len(ids) <= 200):
            raise serializers.ValidationError({"ids": ["Send a list of notification ids, or leave it out to mark everything read."]})
        notifications.mark_read(ids)
        return Response(notifications.summary())
