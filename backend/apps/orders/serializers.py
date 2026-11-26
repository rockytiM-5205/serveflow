import re

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.restaurants.models import PaymentAccount, Restaurant
from apps.reviews.models import Review

from django.db.models import Prefetch

from apps.common.images import media_url

from . import lateness
from .models import Fulfilment, LateFeeStatus, Order, OrderItem, OrderStatus, OrderStatusEvent, Payment, PaymentMethod, PaymentStatus


def normalize_phone(value):
    """"+44 (20) 7946-0958" -> "+442079460958". 7 to 15 digits, optional leading +."""
    text = re.sub(r"[\s().-]", "", value)
    plus = text.startswith("+")
    digits = text[1:] if plus else text
    if not re.fullmatch(r"[0-9]{7,15}", digits):
        raise serializers.ValidationError("Enter a valid phone number.")
    return ("+" if plus else "") + digits


# ------------------------------------------------------------------ customers
class OrderLineSerializer(serializers.Serializer):
    menu_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=99)


class OrderCreateSerializer(serializers.Serializer):
    """Only ids and quantities are accepted. Anything else a client sends (prices, totals,
    status) is ignored: the server prices the order from the menu."""

    customer_name = serializers.CharField(max_length=80)
    customer_phone = serializers.CharField(max_length=30)
    fulfilment_type = serializers.ChoiceField(choices=Fulfilment.choices)
    table_number = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True, default=None)
    accept_late_policy = serializers.BooleanField(required=False, default=False, help_text="Required (true) when the restaurant has a late pickup policy and the order is for pickup. Send true only after showing the customer the policy.")
    pickup_at = serializers.DateTimeField(required=False, allow_null=True, default=None, help_text="Required for pickup: when you will collect it. At least 30 minutes ahead, while the restaurant is open (see pickup-slots).")
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    items = OrderLineSerializer(many=True, allow_empty=False, max_length=30)

    def validate_customer_phone(self, value):
        return normalize_phone(value)

    def to_service_data(self):
        data = self.validated_data
        return {
            "customer_name": data["customer_name"],
            "customer_phone": data["customer_phone"],
            "fulfilment_type": data["fulfilment_type"],
            "table_number": data["table_number"],
            "pickup_at": data["pickup_at"],
            "accept_late_policy": data["accept_late_policy"],
            "notes": data["notes"],
            "lines": [(line["menu_item_id"], line["quantity"]) for line in data["items"]],
        }


class OrderRestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Restaurant
        fields = ("slug", "name")
        read_only_fields = fields


class PublicOrderItemSerializer(serializers.ModelSerializer):
    """One line of an order. The extra fields let the order page draw a plate from what was ordered: the item's own photo if it has one,
    the dish style the restaurant chose (empty means work it out from the name), and the menu category."""

    name = serializers.CharField(source="item_name")
    image_url = serializers.SerializerMethodField(help_text="The item's photo, or null")
    dish_kind = serializers.CharField(source="menu_item.dish_kind", read_only=True)
    category = serializers.CharField(source="menu_item.category.name", read_only=True)

    class Meta:
        model = OrderItem
        fields = ("name", "unit_name", "unit_price", "quantity", "line_total", "image_url", "dish_kind", "category")
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image_url(self, obj):
        return media_url(obj.menu_item.image) or obj.menu_item.image_url


# Load an order's items together with the menu item behind each one, so drawing a plate costs no extra queries.
PUBLIC_ITEMS = Prefetch("items", queryset=OrderItem.objects.select_related("menu_item__category"))


class TimelineEntrySerializer(serializers.ModelSerializer):
    status = serializers.CharField(source="to_status")
    at = serializers.DateTimeField(source="created_at")

    class Meta:
        model = OrderStatusEvent
        fields = ("status", "at")
        read_only_fields = fields


class PaymentInstructionsSerializer(serializers.Serializer):
    """How to pay: the exact amount, the reference to quote, and the restaurant's own account."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()
    reference = serializers.CharField()
    bank_name = serializers.CharField()
    account_name = serializers.CharField()
    account_number = serializers.CharField()
    instructions = serializers.CharField()


class PublicOrderSerializer(serializers.ModelSerializer):
    """What a customer may see about their own order. No name, no phone, no ids, and no staff order number: customers use
    the random reference."""

    restaurant = OrderRestaurantSerializer(read_only=True)
    items = PublicOrderItemSerializer(many=True, read_only=True)
    timeline = TimelineEntrySerializer(source="events", many=True, read_only=True)
    cancellable = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    review = serializers.SerializerMethodField()
    can_review = serializers.SerializerMethodField()
    review_status = serializers.SerializerMethodField(help_text="can_review, sign_in (completed but the viewer isn't a signed-in customer), or empty")
    pickup_policy = serializers.SerializerMethodField()
    late_fee = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "reference", "status", "payment_status", "payment", "review", "can_review", "review_status", "pickup_policy", "late_fee", "fulfilment_type", "table_number", "pickup_at", "pickup_fee",
            "currency", "subtotal", "total", "restaurant", "items", "timeline", "cancellable", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_cancellable(self, order) -> bool:
        return order.status == OrderStatus.PENDING and order.payment_status == PaymentStatus.UNPAID

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_review(self, order):
        """The customer's own review of this order, if they wrote one (plain values only, so it can be saved as JSON)."""
        review = Review.objects.filter(order_id=order.pk).first()
        if review is None:
            return None
        return {"rating": review.rating, "comment": review.comment, "created_at": review.created_at.isoformat(), "status": review.status}

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_pickup_policy(self, order):
        """The late pickup rules this customer accepted, and when the free period ends (null until the restaurant marks it ready)."""
        policy = order.late_policy
        if not policy:
            return None
        until = lateness.free_until(order)
        return {**policy, "free_until": until.isoformat() if until else None, "accepted_at": order.late_policy_accepted_at.isoformat()}

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_late_fee(self, order):
        if order.late_fee_status == LateFeeStatus.NONE:
            return None
        return {"amount": str(order.late_fee), "status": order.late_fee_status}

    def _viewer(self):
        """The signed-in customer looking at this order, if any."""
        user = getattr(self.context.get("request"), "user", None)
        if user is not None and user.is_authenticated and user.is_active:
            return getattr(user, "customer_profile", None)
        return None

    def get_review_status(self, order) -> str:
        """Who may review this order, from the viewer's side. Reviews need a customer account, one review per order and one per restaurant:
        'can_review' for an eligible signed-in customer, 'sign_in' for a completed, unreviewed order seen by someone who isn't signed in, and
        '' when there is nothing to offer (not completed, already reviewed, someone else's order, or this restaurant was already reviewed)."""
        if order.status != OrderStatus.COMPLETED or Review.objects.filter(order_id=order.pk).exists():
            return ""
        customer = self._viewer()
        if customer is None:
            return "sign_in"
        if order.customer_id not in (None, customer.pk):
            return ""
        if Review.objects.filter(restaurant_id=order.restaurant_id, customer=customer).exists():
            return ""
        return "can_review"

    def get_can_review(self, order) -> bool:
        return self.get_review_status(order) == "can_review"

    @extend_schema_field(PaymentInstructionsSerializer(allow_null=True))
    def get_payment(self, order):
        """Shown only while there is something to pay: the order is still waiting and the money hasn't been confirmed."""
        if order.payment_status == PaymentStatus.PAID or order.status not in (OrderStatus.PENDING, OrderStatus.CONFIRMED):
            return None
        account = PaymentAccount.objects.filter(restaurant_id=order.restaurant_id).first()
        if account is None or not account.ready:
            return None
        # Rendered through the serializer so the amount is a string. A raw Decimal here can't be saved with the idempotent
        # response (JSON) and made every checkout fail with a 500.
        return PaymentInstructionsSerializer({
            "amount": order.total, "currency": order.currency, "reference": order.reference, "bank_name": account.bank_name,
            "account_name": account.account_name, "account_number": account.account_number, "instructions": account.instructions,
        }).data


class OrderCreatedSerializer(PublicOrderSerializer):
    token = serializers.CharField(read_only=True)

    class Meta(PublicOrderSerializer.Meta):
        fields = ("token", *PublicOrderSerializer.Meta.fields)
        read_only_fields = fields


# ------------------------------------------------------------------ staff
class StaffOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ("item_name", "unit_name", "unit_price", "quantity", "line_total")
        read_only_fields = fields


class StaffEventSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="actor_user.email", read_only=True, default=None)

    class Meta:
        model = OrderStatusEvent
        fields = ("from_status", "to_status", "actor_type", "actor_email", "reason", "created_at")
        read_only_fields = fields


class StaffPaymentSerializer(serializers.ModelSerializer):
    recorded_by_email = serializers.EmailField(source="recorded_by.email", read_only=True)

    class Meta:
        model = Payment
        fields = ("amount", "currency", "method", "status", "reference", "recorded_by_email", "created_at")
        read_only_fields = fields


class StaffOrderListSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True)
    items = StaffOrderItemSerializer(many=True, read_only=True)
    refund_due = serializers.SerializerMethodField()
    late_free_until = serializers.SerializerMethodField()
    customer_type = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "public_id", "code", "reference", "source", "customer_type", "business_date", "status", "payment_status", "payment_claimed_at",
            "refund_due", "fulfilment_type", "table_number", "pickup_at", "pickup_fee", "late_fee", "late_fee_status",
            "late_free_until", "customer_name", "items", "total",
            "currency", "ready_at", "completed_at", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_customer_type(self, order) -> str:
        """GUEST when the order was placed without a ServeFlow account (and never added to one), otherwise ACCOUNT."""
        return "ACCOUNT" if order.customer_id else "GUEST"

    def get_late_free_until(self, order) -> str | None:
        until = lateness.free_until(order)
        return until.isoformat() if until else None

    def get_refund_due(self, order) -> bool:
        """Paid, then rejected or cancelled: the restaurant owes the customer their money back."""
        return order.payment_status == PaymentStatus.PAID and order.status in (OrderStatus.REJECTED, OrderStatus.CANCELLED)


class StaffOrderDetailSerializer(StaffOrderListSerializer):
    events = StaffEventSerializer(many=True, read_only=True)
    payments = StaffPaymentSerializer(many=True, read_only=True)

    class Meta(StaffOrderListSerializer.Meta):
        fields = (*StaffOrderListSerializer.Meta.fields, "customer_phone", "notes", "subtotal", "events", "payments")
        read_only_fields = fields


class TransitionSerializer(serializers.Serializer):
    to_status = serializers.ChoiceField(
        choices=[
            OrderStatus.CONFIRMED, OrderStatus.REJECTED, OrderStatus.SERVING, OrderStatus.READY_FOR_PICKUP, OrderStatus.COMPLETED,
        ]
    )
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    expected_status = serializers.ChoiceField(choices=OrderStatus.choices, required=False)


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    acknowledge_serving = serializers.BooleanField(required=False, default=False)
    expected_status = serializers.ChoiceField(choices=OrderStatus.choices, required=False)


class BulkPaymentSerializer(serializers.Serializer):
    orders = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50, help_text="public_id of each order, at most 50")
    method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.TRANSFER)
    start_preparing = serializers.BooleanField(default=False, help_text="Also accept the orders and start preparing them right after their payment is confirmed")


class BulkTransitionSerializer(serializers.Serializer):
    orders = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50, help_text="public_id of each order, at most 50")
    to_status = serializers.ChoiceField(choices=[OrderStatus.CONFIRMED, OrderStatus.SERVING, OrderStatus.READY_FOR_PICKUP, OrderStatus.COMPLETED])


class SkippedOrderSerializer(serializers.Serializer):
    public_id = serializers.UUIDField()
    reference = serializers.CharField(required=False)
    reason = serializers.CharField(help_text="payment_required, already_paid, already_there, not_payable, invalid_transition or not_found")


class BulkPaymentResultSerializer(serializers.Serializer):
    confirmed = serializers.ListField(child=serializers.UUIDField())
    skipped = SkippedOrderSerializer(many=True)


class BulkTransitionResultSerializer(serializers.Serializer):
    moved = serializers.ListField(child=serializers.UUIDField())
    skipped = SkippedOrderSerializer(many=True)


class PaymentSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
