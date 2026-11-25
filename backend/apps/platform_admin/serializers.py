"""Response shapes follow docs/owner-api-contract.md. Lists use BaseSerializer so each row is exactly the contract's dict."""
import re

from rest_framework import serializers

from apps.restaurants.models import Restaurant
from apps.restaurants.serializers import RestaurantSettingsSerializer, RestaurantWriteSerializer

from .models import ApiCredential, PaymentDetails, Plan, SubscriptionPayment


def _status(restaurant):
    return "ACTIVE" if restaurant.is_active else "SUSPENDED"


class CustomerSerializer(serializers.BaseSerializer):
    def to_representation(self, r):
        sub = getattr(r, "subscription", None)
        return {
            "id": r.pk, "name": r.name, "account_id": r.slug, "registered_at": r.created_at,
            "plan": {"id": sub.plan_id, "name": sub.plan.name, "is_trial": sub.plan.is_trial} if sub else None,
            "next_plan": {"id": sub.next_plan_id, "name": sub.next_plan.name} if sub and sub.next_plan_id else None,
            "subscription_status": sub.status if sub else None,
            "requests_30d": getattr(r, "requests_30d", 0), "status": _status(r),
            "admin_email": getattr(r, "admin_email", None), "subscription_ends_at": sub.current_period_end if sub else None,
        }


def credential_row(c):
    sub = getattr(c.restaurant, "subscription", None)
    plan = sub.plan if sub else None
    custom = c.rate_limit_per_minute is not None or c.monthly_request_limit is not None
    return {
        "id": c.pk, "prefix": c.prefix, "name": c.name, "customer_name": c.restaurant.name, "environment": c.environment,
        "status": c.status, "last_used_at": c.last_used_at,
        # What is enforced: the key's own number, else the restaurant's current plan.
        "rate_limit_per_minute": c.rate_limit_per_minute if c.rate_limit_per_minute is not None else (plan.rate_limit_per_minute if plan else None),
        "monthly_request_limit": c.monthly_request_limit if c.monthly_request_limit is not None else (plan.included_requests if plan else None),
        "limits_source": "custom" if custom else "plan", "created_at": c.created_at,
        "allowed_actions": ["revoke"] if c.status == ApiCredential.Status.ACTIVE else [],
    }  # never includes secret_hash


class CredentialSerializer(serializers.BaseSerializer):
    def to_representation(self, c):
        return credential_row(c)


class CredentialCreateSerializer(serializers.Serializer):
    customer = serializers.CharField(max_length=63, help_text="The restaurant's account ID (slug).")
    name = serializers.CharField(max_length=60)
    environment = serializers.ChoiceField(choices=ApiCredential.Environment.choices)
    rate_limit_per_minute = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    monthly_request_limit = serializers.IntegerField(min_value=0, required=False, allow_null=True)

    def validate_customer(self, value):
        restaurant = Restaurant.objects.filter(slug=value.strip().lower()).first()
        if restaurant is None:
            raise serializers.ValidationError("No restaurant has that account ID.")
        if not restaurant.is_active:
            raise serializers.ValidationError("This restaurant is suspended.")
        return restaurant

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a name.")
        return value


class PlanSerializer(serializers.ModelSerializer):
    features = serializers.ListField(child=serializers.CharField(max_length=100), required=False, max_length=50)

    class Meta:
        model = Plan
        fields = ("id", "name", "description", "interval", "price", "currency", "included_orders", "included_requests", "rate_limit_per_minute", "pack_orders", "pack_price", "features", "status", "is_trial")
        read_only_fields = ("id", "status", "is_trial")

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a name.")
        return value

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("The price can't be negative.")
        return value

    def validate_rate_limit_per_minute(self, value):
        if value < 1:
            raise serializers.ValidationError("The rate limit must be at least 1.")
        return value

    def validate_currency(self, value):
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise serializers.ValidationError("Use a 3-letter uppercase code such as NGN.")
        return value

    def validate(self, attrs):
        orders = attrs.get("pack_orders", getattr(self.instance, "pack_orders", None))
        price = attrs.get("pack_price", getattr(self.instance, "pack_price", None))
        if (orders is None) != (price is None):
            raise serializers.ValidationError({"pack_orders": ["Set both the order pack size and its price, or neither."]})
        if orders is not None and (orders < 1 or price <= 0):
            raise serializers.ValidationError({"pack_orders": ["An order pack needs at least 1 order and a price above zero."]})
        return attrs

    def validate_features(self, value):
        return [item.strip() for item in value if item.strip()]


class SubscriptionRowSerializer(serializers.BaseSerializer):
    def to_representation(self, s):
        return {
            "id": s.pk, "customer_name": s.restaurant.name, "plan_name": s.plan.name, "next_plan_name": s.next_plan.name if s.next_plan_id else None,
            "status": s.status, "started_at": s.started_at,
            "current_period_start": s.current_period_start, "current_period_end": s.current_period_end, "renews_at": s.current_period_end,
            "payment_status": getattr(s, "payment_status", None), "trial_ends_at": s.trial_ends_at,
            "pending_plan_name": s.pending_plan.name if s.pending_plan_id else None,
            "orders": None if getattr(s, "period_included", None) is None else {
                "included": s.period_included, "extra": s.period_extra or 0, "used": s.period_used or 0,
                "capacity": s.period_included + (s.period_extra or 0),
            },
        }


class PaymentRowSerializer(serializers.BaseSerializer):
    def to_representation(self, p):
        return {
            "id": p.pk, "reference": p.reference, "kind": p.kind, "customer_name": p.subscription.restaurant.name, "amount": p.amount, "currency": p.currency,
            "status": p.status, "provider": p.provider, "provider_reference": p.provider_reference, "failure_reason": p.failure_reason,
            "transacted_at": p.transacted_at,
            "allowed_actions": ["confirm", "fail"] if p.status == SubscriptionPayment.Status.AWAITING_CONFIRMATION else [],
        }


class AuditRowSerializer(serializers.BaseSerializer):
    def to_representation(self, e):
        return {
            "occurred_at": e.created_at, "actor": e.actor.email if e.actor else None, "action": e.action,
            "resource_type": e.resource_type, "resource_id": e.resource_id, "summary": e.summary,
        }


class PaymentDetailsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentDetails
        fields = ("bank_name", "account_name", "account_number", "instructions")

    def validate_account_number(self, value):
        value = value.strip()
        if value and not re.fullmatch(r"\d{6,20}", value):
            raise serializers.ValidationError("Use digits only, 6 to 20 of them.")
        return value

    def validate_instructions(self, value):
        return value.strip()


class OwnerRestaurantCreateSerializer(RestaurantWriteSerializer):
    """A restaurant and its one admin, created together by the platform owner."""

    admin_email = serializers.EmailField(max_length=254)
    admin_first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    admin_last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    admin_password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False, write_only=True,
                                           help_text="Leave blank and a temporary password is generated and shown once.")
    plan_id = serializers.IntegerField(required=False, allow_null=True)
    start_trial = serializers.BooleanField(required=False, default=True)

    class Meta(RestaurantWriteSerializer.Meta):
        fields = (*RestaurantWriteSerializer.Meta.fields, "admin_email", "admin_first_name", "admin_last_name", "admin_password", "plan_id", "start_trial")

    def validate_plan_id(self, value):
        if value is None:
            return None
        plan = Plan.objects.filter(pk=value, status=Plan.Status.ACTIVE, is_trial=False).first()
        if plan is None:
            raise serializers.ValidationError("Choose an active plan.")
        return plan


class OwnerRestaurantUpdateSerializer(RestaurantSettingsSerializer):
    """Everything about the restaurant except its account ID (the slug is part of public links)."""


class AdminUpdateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254, required=False)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
