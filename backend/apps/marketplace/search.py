"""Finding restaurants: by name, by area, by category and by distance. Public data only.

Distance uses the haversine formula in the database, with a bounding-box prefilter so the coordinate index does the first cut.
That is plenty at marketplace scale. When it isn't, replace `distance_km` and `within` with PostGIS (a PointField, `Distance`,
`dwithin`) and nothing else in this module or its callers changes.
"""
import math
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Exists, F, FloatField, OuterRef, Q, Value
from django.db.models.functions import ASin, Cast, Cos, Least, Power, Radians, Sin, Sqrt
from django.utils import timezone

from apps.restaurants.models import OpeningPeriod, Restaurant

EARTH_RADIUS_KM = 6371.0088


def listed_restaurants(now=None):
    """Restaurants a customer may see and order from: switched on by the owner, not suspended, and not locked for billing."""
    now = now or timezone.now()
    grace = timedelta(days=getattr(settings, "BILLING_GRACE_DAYS", 3))
    unlocked = (
        Q(subscription__isnull=True)
        | Q(subscription__status="TRIAL", subscription__current_period_end__gte=now)
        | Q(subscription__status__in=["ACTIVE", "PAST_DUE"], subscription__current_period_end__gte=now - grace)
    )
    return Restaurant.objects.filter(is_active=True, listed_in_marketplace=True).filter(unlocked)


def distance_km(lat, lng):
    """Great-circle distance in km from (lat, lng) to each restaurant, as a database expression. NULL without coordinates."""
    lat2 = Radians(Cast("latitude", FloatField()))
    lng2 = Radians(Cast("longitude", FloatField()))
    lat1, lng1 = Value(math.radians(lat), output_field=FloatField()), Value(math.radians(lng), output_field=FloatField())
    a = Power(Sin((lat2 - lat1) / 2), 2) + Cos(lat1) * Cos(lat2) * Power(Sin((lng2 - lng1) / 2), 2)
    return Value(2 * EARTH_RADIUS_KM, output_field=FloatField()) * ASin(Sqrt(Least(Value(1.0, output_field=FloatField()), a)))


def within(qs, lat, lng, radius_km):
    """Cheap bounding box first (uses the coordinate index), exact distance second."""
    dlat = math.degrees(radius_km / EARTH_RADIUS_KM)
    dlng = math.degrees(radius_km / (EARTH_RADIUS_KM * max(math.cos(math.radians(lat)), 0.01)))
    qs = qs.filter(latitude__gte=lat - dlat, latitude__lte=lat + dlat, longitude__gte=lng - dlng, longitude__lte=lng + dlng)
    return qs.filter(distance__lte=radius_km)


def open_now(qs, now=None):
    """Restaurants taking orders that are inside their published hours, or that haven't published any. Judged per timezone."""
    now = now or timezone.now()
    open_in_zone = Q()
    for zone in set(qs.values_list("timezone", flat=True)):
        local = now.astimezone(ZoneInfo(zone))
        current = local.time().replace(second=0, microsecond=0)
        matching = OpeningPeriod.objects.filter(restaurant=OuterRef("pk"), weekday=local.weekday(), opens__lte=current, closes__gt=current)
        open_in_zone |= Q(timezone=zone) & Exists(matching)
    any_hours = Exists(OpeningPeriod.objects.filter(restaurant=OuterRef("pk")))
    return qs.filter(accepting_orders=True).filter(~any_hours | open_in_zone) if open_in_zone else qs.filter(accepting_orders=True)


def search(params, now=None):
    """params is already validated (see views.SearchParams). Returns a queryset annotated with `distance` (km or NULL)."""
    qs = listed_restaurants(now).prefetch_related("opening_periods")
    if params.get("q"):
        qs = qs.filter(Q(name__icontains=params["q"]) | Q(slug__icontains=params["q"]))
    if params.get("area"):
        qs = qs.filter(Q(area__icontains=params["area"]) | Q(address__icontains=params["area"]))
    if params.get("category"):
        qs = qs.filter(category=params["category"])
    if params.get("open_now"):
        qs = open_now(qs, now)
    lat, lng = params.get("lat"), params.get("lng")
    if lat is not None:
        qs = qs.annotate(distance=distance_km(lat, lng))
        if params.get("radius_km"):
            qs = within(qs, lat, lng, params["radius_km"])
    else:
        qs = qs.annotate(distance=Value(None, output_field=FloatField()))
    ordering = params.get("ordering") or ("distance" if lat is not None else "name")
    if ordering == "distance":
        return qs.order_by(F("distance").asc(nulls_last=True), "name", "id")
    if ordering == "rating":
        return qs.order_by(F("rating_average").desc(nulls_last=True), "name", "id")
    return qs.order_by("name", "id")
