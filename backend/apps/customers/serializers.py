import re

from rest_framework import serializers

from apps.orders.models import OrderStatus
from apps.orders.serializers import PublicOrderSerializer
from apps.orders.tokens import make_token
from apps.reviews.models import Review

PHONE = re.compile(r"^\+?[0-9][0-9 ()-]{5,18}[0-9]$")


class CustomerRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(write_only=True, max_length=128, trim_whitespace=False)
    first_name = serializers.CharField(max_length=60)
    last_name = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")

    def validate_email(self, value):
        return value.strip().lower()

    def validate_phone(self, value):
        value = value.strip()
        if value and not PHONE.match(value):
            raise serializers.ValidationError("Enter a phone number like +2348012345678.")
        return value


class CustomerLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, trim_whitespace=False)


class CustomerUpdateSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=60, required=False)
    last_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)

    validate_phone = CustomerRegisterSerializer.validate_phone


class CustomerPasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class ClaimSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=400)


class CustomerSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    phone = serializers.CharField()


def customer_payload(user):
    return {"email": user.email, "first_name": user.first_name, "last_name": user.last_name, "phone": user.customer_profile.phone}


class CustomerOrderSerializer(serializers.Serializer):
    """One line of someone's order history. `track_token` opens the normal order page (status, payment details, review)."""

    def to_representation(self, order):
        review = Review.objects.filter(order_id=order.pk).exists()
        # one review per restaurant: once this customer has reviewed it, none of their orders from it offer another
        reviewed_restaurant = Review.objects.filter(restaurant_id=order.restaurant_id, customer_id=order.customer_id).exists()
        return {
            "public_id": str(order.public_id), "reference": order.reference, "status": order.status, "payment_status": order.payment_status,
            "fulfilment_type": order.fulfilment_type, "pickup_at": order.pickup_at, "total": order.total, "currency": order.currency,
            "created_at": order.created_at, "restaurant": {"slug": order.restaurant.slug, "name": order.restaurant.name},
            "items_count": sum(item.quantity for item in order.items.all()), "item_names": [item.item_name for item in list(order.items.all())[:3]],
            "active": order.status not in (OrderStatus.COMPLETED, OrderStatus.REJECTED, OrderStatus.CANCELLED),
            "can_review": order.status == OrderStatus.COMPLETED and not review and not reviewed_restaurant, "reviewed": review,
            "track_token": make_token(order),
        }


class CustomerOrderDetailSerializer(PublicOrderSerializer):
    """The same view the order link gives, plus the token, because this is their own order."""

    token = serializers.SerializerMethodField()

    class Meta(PublicOrderSerializer.Meta):
        fields = (*PublicOrderSerializer.Meta.fields, "token")
        read_only_fields = fields

    def get_token(self, order) -> str:
        return make_token(order)
