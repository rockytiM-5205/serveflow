from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.common.images import media_url

from .models import MenuCategory, MenuItem


# ----- staff -----
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuCategory
        fields = ("id", "name", "description", "sort_order", "is_active")
        read_only_fields = ("id",)

    def validate_name(self, value):
        taken = MenuCategory.objects.filter(
            restaurant=self.context["request"].restaurant, name__iexact=value
        )
        if self.instance:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("A category with this name already exists.")
        return value


class RestaurantCategoryField(serializers.PrimaryKeyRelatedField):
    """Only categories of the caller's restaurant are accepted."""

    def get_queryset(self):
        return MenuCategory.objects.filter(restaurant=self.context["request"].restaurant)


class ItemSerializer(serializers.ModelSerializer):
    category = RestaurantCategoryField(queryset=MenuCategory.objects.all())
    archived = serializers.BooleanField(source="is_archived", read_only=True)
    image = serializers.SerializerMethodField(help_text="Path of the uploaded photo, or null. Upload with POST .../image/.")

    class Meta:
        model = MenuItem
        fields = (
            "id", "category", "name", "description", "price", "unit_name",
            "is_available", "dish_kind", "image_url", "image", "archived", "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image(self, obj):
        return media_url(obj.image)

    def validate_name(self, value):
        if self.instance and self.instance.is_archived:
            return value
        taken = MenuItem.objects.filter(
            restaurant=self.context["request"].restaurant, name__iexact=value, archived_at__isnull=True
        )
        if self.instance:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("An item with this name already exists.")
        return value

    def validate_image_url(self, value):
        # DRF drops the model's https-only validator, so it is enforced here as well.
        if not value:
            return None
        if not value.startswith("https://"):
            raise serializers.ValidationError("Use a link that starts with https://")
        return value


class AvailabilitySerializer(serializers.Serializer):
    is_available = serializers.BooleanField()


# ----- public (customers) -----
class PublicItemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField(help_text="The uploaded photo if there is one, else an older photo link, else null.")

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image_url(self, obj):
        return media_url(obj.image) or obj.image_url

    class Meta:
        model = MenuItem
        fields = ("id", "name", "description", "price", "unit_name", "is_available", "image_url")
        read_only_fields = fields


class PublicCategorySerializer(serializers.ModelSerializer):
    items = PublicItemSerializer(many=True, read_only=True)

    class Meta:
        model = MenuCategory
        fields = ("id", "name", "description", "items")
        read_only_fields = fields


class PublicMenuRestaurantSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    currency = serializers.CharField()


class PublicMenuSerializer(serializers.Serializer):
    restaurant = PublicMenuRestaurantSerializer()
    categories = PublicCategorySerializer(many=True)
