"""Public marketplace endpoints. No sign-in: browsing never needs an account."""
from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.common.images import media_url
from apps.restaurants import hours
from apps.restaurants.models import RestaurantCategory
from apps.restaurants.serializers import category_of

from . import search

PAGE_SIZE_DEFAULT, PAGE_SIZE_MAX = 12, 48


class SearchParams(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, max_length=80)
    area = serializers.CharField(required=False, allow_blank=True, max_length=120)
    category = serializers.ChoiceField(choices=RestaurantCategory.choices, required=False)
    lat = serializers.FloatField(required=False, min_value=-90, max_value=90)
    lng = serializers.FloatField(required=False, min_value=-180, max_value=180)
    radius_km = serializers.FloatField(required=False, min_value=0.1, max_value=200)
    open_now = serializers.BooleanField(required=False)
    ordering = serializers.ChoiceField(choices=["distance", "name", "rating"], required=False)
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=PAGE_SIZE_MAX, default=PAGE_SIZE_DEFAULT)

    def validate(self, attrs):
        if ("lat" in attrs) != ("lng" in attrs):
            raise serializers.ValidationError({"lat": "Send both lat and lng, or neither."})
        if "radius_km" in attrs and "lat" not in attrs:
            raise serializers.ValidationError({"radius_km": "A distance limit needs lat and lng."})
        if attrs.get("ordering") == "distance" and "lat" not in attrs:
            raise serializers.ValidationError({"ordering": "Sorting by distance needs lat and lng."})
        for key in ("q", "area"):
            if key in attrs:
                attrs[key] = attrs[key].strip()
        return attrs


class MarketplaceCategoryRefSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class MarketplaceCardSerializer(serializers.Serializer):
    slug = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    category = MarketplaceCategoryRefSerializer(allow_null=True)
    area = serializers.CharField()
    address = serializers.CharField()
    logo_url = serializers.CharField(allow_null=True)
    cover_url = serializers.CharField(allow_null=True)
    distance_km = serializers.FloatField(allow_null=True, help_text="Only when lat and lng were sent and the restaurant has coordinates.")
    availability = serializers.ChoiceField(choices=["OPEN", "CLOSED", "PAUSED"])
    is_open_now = serializers.BooleanField(allow_null=True, help_text="null when the restaurant hasn't published opening hours.")
    rating_average = serializers.FloatField(allow_null=True, help_text="null until the restaurant has verified reviews.")
    rating_count = serializers.IntegerField()
    pickup_enabled = serializers.BooleanField()
    dine_in_enabled = serializers.BooleanField()


class MarketplaceSearchResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    has_next = serializers.BooleanField()
    results = MarketplaceCardSerializer(many=True)


class MarketplaceCategoryRowSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()


class MarketplaceCategoriesResponseSerializer(serializers.Serializer):
    results = MarketplaceCategoryRowSerializer(many=True)


class MarketplaceAreaRowSerializer(serializers.Serializer):
    area = serializers.CharField()
    count = serializers.IntegerField()


class MarketplaceAreasResponseSerializer(serializers.Serializer):
    results = MarketplaceAreaRowSerializer(many=True)


def card(restaurant):
    """What a list card needs, and nothing internal. A rating appears only when real reviews exist."""
    km = getattr(restaurant, "distance", None)
    return {
        "slug": restaurant.slug, "name": restaurant.name, "description": restaurant.description[:160],
        "category": category_of(restaurant), "area": restaurant.area, "address": restaurant.address,
        "logo_url": media_url(restaurant.logo), "cover_url": media_url(restaurant.cover_image),
        "distance_km": round(km, 1) if km is not None else None,
        "availability": hours.availability(restaurant), "is_open_now": hours.is_open_now(restaurant),
        "rating_average": float(restaurant.rating_average) if restaurant.rating_average is not None else None,
        "rating_count": restaurant.rating_count,
        "pickup_enabled": restaurant.pickup_enabled, "dine_in_enabled": restaurant.dine_in_enabled,
    }


class PublicMarketplaceView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "marketplace"


class RestaurantSearchView(PublicMarketplaceView):
    @extend_schema(
        parameters=[SearchParams], responses=MarketplaceSearchResponseSerializer,
        summary="Find restaurants by name, area, category or distance. Location is optional.",
    )
    def get(self, request):
        params = SearchParams(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        qs = search.search(data)
        size, page = data["page_size"], data["page"]
        total = qs.count()
        rows = list(qs[(page - 1) * size: page * size])
        return Response({
            "count": total, "page": page, "page_size": size, "has_next": page * size < total,
            "results": [card(r) for r in rows],
        })


class CategoryListView(PublicMarketplaceView):
    @extend_schema(responses=MarketplaceCategoriesResponseSerializer, summary="Categories that have at least one listed restaurant, with counts")
    def get(self, request):
        counts = dict(search.listed_restaurants().exclude(category="").values_list("category").annotate(n=Count("id")))
        return Response({"results": [
            {"value": c.value, "label": c.label, "count": counts[c.value]} for c in RestaurantCategory if c.value in counts
        ]})


class AreaListView(PublicMarketplaceView):
    @extend_schema(responses=MarketplaceAreasResponseSerializer, summary="Areas that have at least one listed restaurant, for manual location search")
    def get(self, request):
        rows = search.listed_restaurants().exclude(area="").values_list("area").annotate(n=Count("id")).order_by("-n", "area")[:50]
        return Response({"results": [{"area": area, "count": n} for area, n in rows]})
