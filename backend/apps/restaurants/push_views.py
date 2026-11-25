"""Order alerts: a device subscribes (or stops) here. Mounted under /api/v1/restaurants/<slug>/push/."""
from urllib.parse import urlparse

from django.conf import settings
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from apps.common.schema import SLUG_PARAM

from . import push
from .models import MembershipRole, PushSubscription, Restaurant
from .permissions import RestaurantScopedMixin


class SubscribeSerializer(serializers.Serializer):
    endpoint = serializers.CharField(max_length=1000)
    p256dh = serializers.CharField(max_length=200)
    auth = serializers.CharField(max_length=100)

    def validate_endpoint(self, value):
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise serializers.ValidationError("This isn't a valid push address.")
        return value


class EndpointSerializer(serializers.Serializer):
    endpoint = serializers.CharField(max_length=1000)


class PushConfigSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    public_key = serializers.CharField(allow_blank=True)
    devices = serializers.IntegerField(help_text="How many of your devices have alerts on for this restaurant")


class PushStateSerializer(serializers.Serializer):
    subscribed = serializers.BooleanField()


class PushSentSerializer(serializers.Serializer):
    sent = serializers.IntegerField()
    enabled = serializers.BooleanField()


class PushBase(RestaurantScopedMixin, GenericAPIView):
    min_role = MembershipRole.STAFF  # everyone on the team can get alerts on their own device
    queryset = Restaurant.objects.none()


class PushConfigView(PushBase):
    serializer_class = PushConfigSerializer

    @extend_schema(parameters=[SLUG_PARAM], summary="Whether order alerts are available, and the public key a device needs to subscribe", responses=PushConfigSerializer)
    def get(self, request, *args, **kwargs):
        mine = PushSubscription.objects.filter(restaurant=request.restaurant, user=request.user).count()
        return Response({"enabled": push.enabled(), "public_key": settings.VAPID_PUBLIC_KEY if push.enabled() else "", "devices": mine})


class PushSubscribeView(PushBase):
    serializer_class = SubscribeSerializer

    @extend_schema(parameters=[SLUG_PARAM], request=SubscribeSerializer, summary="Turn order alerts on for this device", responses=PushStateSerializer)
    def post(self, request, *args, **kwargs):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with transaction.atomic():
            PushSubscription.objects.update_or_create(
                endpoint=data["endpoint"],  # the same device always has the same address: moving restaurant or user just updates it
                defaults={"restaurant": request.restaurant, "user": request.user, "p256dh": data["p256dh"], "auth": data["auth"],
                          "user_agent": request.headers.get("User-Agent", "")[:200]},
            )
        return Response({"subscribed": True})


class PushUnsubscribeView(PushBase):
    serializer_class = EndpointSerializer

    @extend_schema(parameters=[SLUG_PARAM], request=EndpointSerializer, summary="Turn order alerts off for this device", responses=PushStateSerializer)
    def post(self, request, *args, **kwargs):
        serializer = EndpointSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        PushSubscription.objects.filter(
            restaurant=request.restaurant, user=request.user, endpoint=serializer.validated_data["endpoint"]
        ).delete()
        return Response({"subscribed": False})


class PushTestView(PushBase):
    serializer_class = PushSentSerializer

    @extend_schema(parameters=[SLUG_PARAM], summary="Send a test alert to your own devices", request=None, responses=PushSentSerializer)
    def post(self, request, *args, **kwargs):
        if not push.enabled():
            return Response({"sent": 0, "enabled": False})
        mine = list(PushSubscription.objects.filter(restaurant=request.restaurant, user=request.user))
        sent = push.send_to(mine, {"title": "ServeFlow alerts are on", "body": "You will see a message like this for every new order.",
                                   "url": push.DASHBOARD_ORDERS, "tag": "test", "icon": push.ICON})
        return Response({"sent": sent, "enabled": True})
