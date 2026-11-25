"""Billing routes. Public: GET /api/v1/billing/plans/. Restaurant owners: /api/v1/restaurants/<slug>/billing/..."""
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.restaurants.models import MembershipRole
from apps.restaurants.permissions import RestaurantScopedMixin

from . import billing, webhooks
from .billing import _payment_row
from .models import Plan
from .services import trial_days


def hidden(*methods):
    return extend_schema_view(**{m: extend_schema(exclude=True) for m in methods})


@hidden("get")
class PublicPlansView(APIView):
    """Anyone, signed in or not, can see what's on offer and how payment works."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"plans": billing.active_plans(), "payment": billing.public_payment_info(), "trial_days": trial_days()})


@hidden("get")
class BillingView(RestaurantScopedMixin, APIView):
    min_role = MembershipRole.OWNER

    def get(self, request, slug):
        return Response(billing.overview(request.restaurant))


@hidden("post")
class SubscribeView(RestaurantScopedMixin, APIView):
    min_role = MembershipRole.OWNER

    def post(self, request, slug):
        data = request.data if isinstance(request.data, dict) else {}
        plan_id = data.get("plan_id")
        if not isinstance(plan_id, int) or isinstance(plan_id, bool):
            raise serializers.ValidationError({"plan_id": ["Choose a plan."]})
        plan = Plan.objects.filter(pk=plan_id).first()
        if plan is None:
            raise serializers.ValidationError({"plan_id": ["That plan doesn't exist."]})
        billing.choose_plan(request.restaurant, plan, request.user)
        return Response(billing.overview(request.restaurant), status=201)


@hidden("post")
class ReportPaymentView(RestaurantScopedMixin, APIView):
    min_role = MembershipRole.OWNER

    def post(self, request, slug):
        payment, created = billing.open_payment(request.restaurant, request.user)
        return Response({"payment": _payment_row(payment)}, status=201 if created else 200)


@hidden("post")
class OrderPackPurchaseView(RestaurantScopedMixin, APIView):
    """Start buying an order pack for the running billing period. It adds capacity only after the payment is confirmed."""

    min_role = MembershipRole.OWNER

    def post(self, request, slug):
        payment, pack, created = billing.purchase_order_pack(request.restaurant, request.user)
        return Response({"payment": _payment_row(payment), "order_pack": billing._pack_row(pack)}, status=201 if created else 200)


@hidden("post")
class PlanChangeCancelView(RestaurantScopedMixin, APIView):
    min_role = MembershipRole.OWNER

    def post(self, request, slug):
        billing.cancel_pending_change(request.restaurant, request.user)
        return Response(billing.overview(request.restaurant))


@hidden("post")
class PaymentWebhookView(APIView):
    """Signed notifications from the payment provider. No sign-in: the signature is the credential."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_webhook"

    @classmethod
    def as_view(cls, **initkwargs):
        return csrf_exempt(super().as_view(**initkwargs))

    def post(self, request, provider):
        raw = request.body  # read before anything parses it: the signature covers these exact bytes
        try:
            status, outcome = webhooks.handle(provider, raw, request.headers.get("X-Signature", ""))
        except webhooks.WebhookError as exc:
            return Response({"error": {"code": exc.code, "message": exc.message, "details": {}}}, status=exc.status)
        return Response({"status": status, "outcome": outcome})
