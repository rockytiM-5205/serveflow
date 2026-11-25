from django.contrib.auth import get_user_model
import re

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.common.images import media_url

from . import hours
from .models import MembershipRole, PaymentAccount, Restaurant, RestaurantCategory, RestaurantMembership
from .validators import CURRENCY_PATTERN, ORDER_PREFIX_PATTERN

User = get_user_model()


class MemberUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name")
        read_only_fields = fields


class MemberSerializer(serializers.ModelSerializer):
    user = MemberUserSerializer(read_only=True)

    class Meta:
        model = RestaurantMembership
        fields = ("id", "user", "role", "is_active", "created_at")
        read_only_fields = fields


class PictureUrlsMixin(serializers.Serializer):
    """logo_url and cover_url: public paths of the uploaded pictures, or null."""

    logo_url = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_logo_url(self, obj):
        return media_url(obj.logo)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_cover_url(self, obj):
        return media_url(obj.cover_image)


def category_of(restaurant):
    if not restaurant.category:
        return None
    return {"value": restaurant.category, "label": RestaurantCategory(restaurant.category).label}


class PublicRestaurantSerializer(PictureUrlsMixin, serializers.ModelSerializer):
    """Customer-facing restaurant details. Nothing internal: no members, no ids."""

    category = serializers.SerializerMethodField()
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    rating_average = serializers.FloatField(read_only=True)
    availability = serializers.SerializerMethodField()
    is_open_now = serializers.SerializerMethodField()
    hours = serializers.SerializerMethodField()
    pickup_min_minutes = serializers.SerializerMethodField()
    late_policy = serializers.SerializerMethodField()

    class Meta:
        model = Restaurant
        fields = (
            "slug", "name", "description", "contact_phone", "address", "area", "category", "latitude", "longitude",
            "currency", "timezone", "accepting_orders", "availability", "is_open_now", "hours",
            "rating_average", "rating_count", "pickup_enabled", "pickup_fee", "pickup_min_minutes", "late_policy", "dine_in_enabled",
            "requires_table_number", "logo_url", "cover_url",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_category(self, obj):
        return category_of(obj)

    @extend_schema_field(serializers.IntegerField())
    def get_pickup_min_minutes(self, obj):
        return hours.pickup_lead_minutes()

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_late_policy(self, obj):
        """The late pickup rules, or null when the restaurant has none. Shown to the customer before they order."""
        if not obj.late_fee_enabled:
            return None
        return {
            "grace_minutes": obj.late_grace_minutes, "fee_amount": str(obj.late_fee_amount),
            "interval_minutes": obj.late_fee_interval_minutes, "max_fee": str(obj.late_fee_max),
        }

    @extend_schema_field(serializers.CharField())
    def get_availability(self, obj):
        return hours.availability(obj)

    @extend_schema_field(serializers.BooleanField(allow_null=True))
    def get_is_open_now(self, obj):
        return hours.is_open_now(obj)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_hours(self, obj):
        return hours.hours_table(obj)


class MemberCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    role = serializers.ChoiceField(choices=MembershipRole.choices, default=MembershipRole.STAFF)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    password = serializers.CharField(
        write_only=True, required=False, allow_blank=True, trim_whitespace=False, max_length=128, default="",
        help_text="Starting password for a new account. Ignored if the person already has an account.",
    )


class MemberUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=MembershipRole.choices, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Send role and/or is_active.")
        return attrs


class RestaurantWriteSerializer(serializers.ModelSerializer):
    """Fields a restaurant is created with. Mirrors the database CHECK constraints."""

    currency = serializers.CharField(min_length=3, max_length=3)
    order_prefix = serializers.CharField(
        min_length=3, max_length=5, required=False,
        help_text="3 to 5 capitals or digits starting with a letter. Left out, one is made from the name. Locked once the restaurant has orders.",
    )

    class Meta:
        model = Restaurant
        fields = (
            "name", "slug", "order_prefix", "description", "contact_phone", "address", "currency", "timezone",
            "pickup_enabled", "dine_in_enabled", "requires_table_number",
        )

    def validate_currency(self, value):
        value = value.upper()
        if not re.fullmatch(CURRENCY_PATTERN, value):
            raise serializers.ValidationError("Use a 3-letter code such as USD.")
        return value

    def validate_order_prefix(self, value):
        value = value.strip().upper()
        if not re.fullmatch(ORDER_PREFIX_PATTERN, value):
            raise serializers.ValidationError("Use 3 to 5 capital letters or digits, starting with a letter.")
        current = self.instance
        if current is not None and value != current.order_prefix and current.orders.exists():
            raise serializers.ValidationError("This can't change once the restaurant has taken orders.")
        if Restaurant.objects.filter(order_prefix=value).exclude(pk=getattr(current, "pk", None)).exists():
            raise serializers.ValidationError("Another restaurant already uses this. Try a different one.")
        return value

    def validate(self, attrs):
        current = self.instance

        def value(name, default):
            return attrs.get(name, getattr(current, name) if current else default)

        pickup = value("pickup_enabled", True)
        dine_in = value("dine_in_enabled", False)
        table = value("requires_table_number", False)
        errors = {}
        if not pickup and not dine_in:
            errors["pickup_enabled"] = "Enable at least one way for customers to order."
        if table and not dine_in:
            errors["requires_table_number"] = "Table numbers only apply when dine-in is enabled."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class RestaurantSettingsSerializer(PictureUrlsMixin, RestaurantWriteSerializer):
    """Editable settings. The slug is shown but cannot change: it is part of public links."""

    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True, min_value=-90, max_value=90)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True, min_value=-180, max_value=180)
    category = serializers.ChoiceField(choices=RestaurantCategory.choices, required=False, allow_blank=True)
    pickup_fee = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0, required=False)
    late_fee_amount = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0, required=False)
    late_fee_max = serializers.DecimalField(max_digits=8, decimal_places=2, min_value=0, required=False)
    late_grace_minutes = serializers.IntegerField(min_value=0, max_value=240, required=False)
    late_fee_interval_minutes = serializers.IntegerField(min_value=5, max_value=240, required=False)
    order_prefix_locked = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField())
    def get_order_prefix_locked(self, obj):
        return obj.orders.exists()

    class Meta(RestaurantWriteSerializer.Meta):
        fields = (
            *RestaurantWriteSerializer.Meta.fields, "accepting_orders", "auto_accept_orders", "pickup_fee", "late_fee_enabled", "late_grace_minutes",
            "late_fee_amount", "late_fee_interval_minutes", "late_fee_max", "category", "area", "latitude", "longitude",
            "listed_in_marketplace", "logo_url", "cover_url", "order_prefix_locked",
        )
        read_only_fields = ("slug",)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        current = self.instance

        def value(name):
            return attrs.get(name, getattr(current, name, None) if current else None)

        if value("late_fee_enabled"):
            amount, cap = value("late_fee_amount") or 0, value("late_fee_max") or 0
            if amount <= 0:
                raise serializers.ValidationError({"late_fee_amount": "Set the late fee above zero, or switch the policy off."})
            if cap < amount:
                raise serializers.ValidationError({"late_fee_max": "The maximum can't be less than one late fee."})
        lat, lng = value("latitude"), value("longitude")
        if (lat is None) != (lng is None):
            raise serializers.ValidationError({"latitude": "Set both latitude and longitude, or neither."})
        if attrs.get("accepting_orders") and current is not None:
            account = PaymentAccount.objects.filter(restaurant=current).first()
            if not (account and account.ready):
                raise serializers.ValidationError({"accepting_orders": "Add your bank account details before you start taking orders. Customers pay before you prepare their order."})
        if value("listed_in_marketplace") and not ((value("area") or "").strip() or (value("address") or "").strip()):
            raise serializers.ValidationError({"listed_in_marketplace": "Add your address or area before listing your restaurant in the marketplace."})
        return attrs

    def validate_area(self, value):
        return value.strip()


class OpeningPeriodSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6, help_text="0 is Monday, 6 is Sunday.")
    opens = serializers.CharField(help_text="Local time, HH:MM.")
    closes = serializers.CharField(help_text="Local time, HH:MM. Must be after opens; a period can't cross midnight.")


class OpeningDaySerializer(serializers.Serializer):
    weekday = serializers.IntegerField()
    day = serializers.CharField()
    periods = OpeningPeriodSerializer(many=True)


class OpeningHoursSerializer(serializers.Serializer):
    timezone = serializers.CharField()
    hours = OpeningDaySerializer(many=True)


class OpeningHoursUpdateSerializer(serializers.Serializer):
    periods = OpeningPeriodSerializer(many=True)


class PaymentAccountSerializer(serializers.ModelSerializer):
    ready = serializers.BooleanField(read_only=True)

    class Meta:
        model = PaymentAccount
        fields = ("bank_name", "account_name", "account_number", "instructions", "ready")
        extra_kwargs = {"instructions": {"required": False, "allow_blank": True}}

    def validate_account_number(self, value):
        value = value.strip()
        if not re.fullmatch(r"[0-9A-Za-z ]{4,34}", value):
            raise serializers.ValidationError("Use 4 to 34 letters and digits.")
        return value

    def validate_bank_name(self, value):
        return value.strip()

    def validate_account_name(self, value):
        return value.strip()
