from django.db import IntegrityError, transaction
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import (
    CreateAPIView, GenericAPIView, ListCreateAPIView, RetrieveAPIView, RetrieveUpdateAPIView,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from apps.common.throttles import ScopedRateThrottle

from apps.audit.services import record
from apps.common.images import ImageRejected, process_image
from apps.common.pagination import DefaultCursorPagination
from apps.common.schema import SLUG_PARAM, staff_schema
from apps.platform_admin.notifications import notify

from . import hours
from .models import MembershipRole, OpeningPeriod, PaymentAccount, Restaurant, RestaurantMembership
from .permissions import ROLE_RANK, CanCreateRestaurant, RestaurantScopedMixin
from .serializers import (
    MemberCreateSerializer, MemberSerializer, MemberUpdateSerializer, PublicRestaurantSerializer,
    OpeningHoursSerializer, OpeningHoursUpdateSerializer, PaymentAccountSerializer, RestaurantSettingsSerializer,
    RestaurantWriteSerializer,
)
from .services import add_member, change_member, create_restaurant


class MembersPagination(DefaultCursorPagination):
    ordering = ("created_at", "id")


@staff_schema(get="List the restaurant's members (manager or owner)")
class MemberListView(RestaurantScopedMixin, ListCreateAPIView):
    min_role = MembershipRole.MANAGER
    queryset = RestaurantMembership.objects.select_related("user")
    serializer_class = MemberSerializer
    pagination_class = MembersPagination

    @extend_schema(
        parameters=[SLUG_PARAM], request=MemberCreateSerializer, responses={201: MemberSerializer},
        summary="Add a member. Managers add staff; owners add any role.",
    )
    def post(self, request, *args, **kwargs):
        serializer = MemberCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = add_member(restaurant=request.restaurant, actor=request.membership, **serializer.validated_data)
        return Response(MemberSerializer(membership).data, status=201)


class MemberDetailView(RestaurantScopedMixin, GenericAPIView):
    min_role = MembershipRole.MANAGER
    queryset = RestaurantMembership.objects.select_related("user")
    serializer_class = MemberUpdateSerializer
    http_method_names = ["patch", "options"]

    @extend_schema(
        parameters=[SLUG_PARAM], request=MemberUpdateSerializer, responses=MemberSerializer,
        summary="Change a member's role or deactivate/reactivate them",
    )
    def patch(self, request, *args, **kwargs):
        target = self.get_object()
        serializer = MemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = change_member(
            restaurant=request.restaurant, actor=request.membership, target=target, **serializer.validated_data
        )
        return Response(MemberSerializer(updated).data)


@staff_schema(
    get="Restaurant settings",
    patch="Update settings. Staff may only change accepting_orders; managers and owners may change all.",
)
class RestaurantSettingsView(RestaurantScopedMixin, RetrieveUpdateAPIView):
    min_role = MembershipRole.STAFF
    queryset = Restaurant.objects.all()
    serializer_class = RestaurantSettingsSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Restaurant.objects.none()
        return Restaurant.objects.filter(pk=self.request.restaurant.pk)

    def get_object(self):
        restaurant = self.get_queryset().get()
        self.check_object_permissions(self.request, restaurant)
        return restaurant

    def perform_update(self, serializer):
        if ROLE_RANK[self.request.membership.role] < ROLE_RANK[MembershipRole.MANAGER]:
            if set(self.request.data) - {"accepting_orders"}:
                raise PermissionDenied("Only managers and owners can change these settings.", code="insufficient_role")
        before = {name: getattr(serializer.instance, name) for name in serializer.validated_data}
        with transaction.atomic():
            restaurant = serializer.save()
            changed = sorted(name for name, old in before.items() if getattr(restaurant, name) != old)
            if changed:
                record(
                    restaurant=restaurant, actor=self.request.user, action="restaurant.settings_changed",
                    entity_type="restaurant", entity_id=restaurant.pk, metadata={"changed": changed},
                )
            if "listed_in_marketplace" in changed and restaurant.listed_in_marketplace and not restaurant.marketplace_approved:
                notify("marketplace_review", f"{restaurant.name} wants to be in the marketplace", "Check the restaurant, then approve it.",
                       "#/customers", restaurant, f"marketplace_review:{restaurant.pk}")


class RestaurantCreateView(CreateAPIView):
    """Any signed-in user who is allowed to (see can_create_restaurant) can open a restaurant."""

    permission_classes = [CanCreateRestaurant]
    serializer_class = RestaurantWriteSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "restaurant_create"

    @extend_schema(
        request=RestaurantWriteSerializer, responses={201: PublicRestaurantSerializer},
        summary="Create a restaurant; the caller becomes its owner",
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            restaurant = create_restaurant(request.user, serializer.validated_data)
        except IntegrityError:
            raise ValidationError({"slug": ["This address is already taken."]}) from None
        return Response(PublicRestaurantSerializer(restaurant).data, status=201)


class PublicRestaurantView(RetrieveAPIView):
    """Public restaurant details by slug. Suspended restaurants look like they do not exist."""

    authentication_classes = []
    permission_classes = [AllowAny]
    queryset = Restaurant.objects.filter(is_active=True).prefetch_related("opening_periods")
    serializer_class = PublicRestaurantSerializer
    lookup_field = "slug"


UPLOAD_BODY = {"multipart/form-data": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}, "required": ["file"]}}


class RestaurantPictureView(RestaurantScopedMixin, GenericAPIView):
    """Upload (POST, multipart field "file") or remove (DELETE) the restaurant's logo or cover picture, shown on its public page.
    Managers and owners only. JPEG, PNG or WebP up to 3 MB; checked, resized and re-encoded as WebP before it is stored."""

    min_role = MembershipRole.MANAGER
    queryset = Restaurant.objects.none()
    serializer_class = RestaurantSettingsSerializer
    parser_classes = [MultiPartParser]
    http_method_names = ["post", "delete", "options"]
    kind = "logo"  # "logo" or "cover"; set per route in urls.py

    @property
    def field(self):
        return "logo" if self.kind == "logo" else "cover_image"

    def _swap(self, request, new_content):
        restaurant = request.restaurant
        stored = getattr(restaurant, self.field)
        old = stored.name if stored else None
        with transaction.atomic():
            if new_content is None:
                setattr(restaurant, self.field, None)
            else:
                getattr(restaurant, self.field).save(new_content.name, new_content, save=False)
            restaurant.save(update_fields=[self.field])
            record(
                restaurant=restaurant, actor=request.user, action=f"restaurant.{self.kind}_{'removed' if new_content is None else 'changed'}",
                entity_type="restaurant", entity_id=restaurant.pk, metadata={},
            )
        if old:
            stored.storage.delete(old)  # after the commit, so a failed save never loses the old picture
        return Response(RestaurantSettingsSerializer(restaurant).data)

    @extend_schema(parameters=[SLUG_PARAM], request=UPLOAD_BODY, responses=RestaurantSettingsSerializer, summary="Upload the restaurant's picture (manager or owner)")
    def post(self, request, *args, **kwargs):
        try:
            content = process_image(request.FILES.get("file"), self.kind)
        except ImageRejected as err:
            raise ValidationError({"file": [err.message]}) from None
        return self._swap(request, content)

    @extend_schema(parameters=[SLUG_PARAM], request=None, responses=RestaurantSettingsSerializer, summary="Remove the restaurant's picture (manager or owner)")
    def delete(self, request, *args, **kwargs):
        if not getattr(request.restaurant, self.field):
            return Response(RestaurantSettingsSerializer(request.restaurant).data)
        return self._swap(request, None)


@extend_schema_view(
    get=extend_schema(parameters=[SLUG_PARAM], responses=OpeningHoursSerializer, summary="Opening hours"),
    put=extend_schema(parameters=[SLUG_PARAM], request=OpeningHoursUpdateSerializer, responses=OpeningHoursSerializer,
                      summary="Replace the opening hours (manager or owner)"),
)
class HoursView(RestaurantScopedMixin, GenericAPIView):
    """The restaurant's opening hours. GET (any staff) and PUT (manager or owner) replace-all: send every period you want kept.
    Times are the restaurant's local time. An empty list means "no published hours" (the restaurant is shown by its on/off switch only)."""

    min_role = MembershipRole.MANAGER
    min_roles = {"GET": MembershipRole.STAFF}
    queryset = Restaurant.objects.none()
    serializer_class = OpeningHoursSerializer
    http_method_names = ["get", "put", "head", "options"]

    def get(self, request, *args, **kwargs):
        return Response({"timezone": request.restaurant.timezone, "hours": hours.hours_table(request.restaurant)})

    def put(self, request, *args, **kwargs):
        rows = request.data.get("periods") if isinstance(request.data, dict) else None
        if not isinstance(rows, list):
            raise ValidationError({"periods": ["Send a list of periods."]})
        try:
            clean = hours.validate_periods(rows)
        except ValueError as err:
            raise ValidationError({"periods": [str(err)]}) from None
        restaurant = request.restaurant
        with transaction.atomic():
            OpeningPeriod.objects.filter(restaurant=restaurant).delete()
            OpeningPeriod.objects.bulk_create([OpeningPeriod(restaurant=restaurant, weekday=d, opens=o, closes=c) for d, o, c in clean])
            record(
                restaurant=restaurant, actor=request.user, action="restaurant.hours_changed", entity_type="restaurant",
                entity_id=restaurant.pk, metadata={"periods": len(clean)},
            )
        restaurant = Restaurant.objects.prefetch_related("opening_periods").get(pk=restaurant.pk)
        return Response({"timezone": restaurant.timezone, "hours": hours.hours_table(restaurant)})


@extend_schema_view(
    get=extend_schema(parameters=[SLUG_PARAM], responses=PaymentAccountSerializer, summary="The bank account customers pay into"),
    put=extend_schema(parameters=[SLUG_PARAM], request=PaymentAccountSerializer, responses=PaymentAccountSerializer,
                      summary="Set the bank account customers pay into (owner)"),
)
class PaymentAccountView(RestaurantScopedMixin, GenericAPIView):
    """Customers pay before an order is prepared, so every restaurant gives its account details here. Staff can read them
    (to check an incoming transfer); only the owner changes them."""

    min_role = MembershipRole.OWNER
    min_roles = {"GET": MembershipRole.STAFF}
    queryset = PaymentAccount.objects.none()
    serializer_class = PaymentAccountSerializer
    http_method_names = ["get", "put", "head", "options"]

    def get(self, request, *args, **kwargs):
        account = PaymentAccount.objects.filter(restaurant=request.restaurant).first()
        if account is None:
            return Response({"bank_name": "", "account_name": "", "account_number": "", "instructions": "", "ready": False})
        return Response(PaymentAccountSerializer(account).data)

    def put(self, request, *args, **kwargs):
        existing = PaymentAccount.objects.filter(restaurant=request.restaurant).first()
        serializer = PaymentAccountSerializer(existing, data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            account = serializer.save(restaurant=request.restaurant)
            record(  # the audit log notes that it changed, never the account number itself
                restaurant=request.restaurant, actor=request.user, action="restaurant.payment_account_changed",
                entity_type="restaurant", entity_id=request.restaurant.pk, metadata={"bank_name": account.bank_name},
            )
            if existing is not None:  # customers are told to pay into this account, so the platform owner is told when it changes
                notify("payment_account_changed", f"{request.restaurant.name} changed its bank details",
                       "Customers now pay into the new account. Check that this was expected.", "#/customers", request.restaurant)
        return Response(PaymentAccountSerializer(account).data)
