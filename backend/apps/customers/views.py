from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.db import IntegrityError, transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.throttles import LoginEmailThrottle, LoginIPThrottle
from apps.common.authentication import CsrfSessionAuthentication, enforce_csrf
from apps.common.exceptions import Conflict
from apps.common.pagination import DefaultCursorPagination
from apps.orders.models import Order, OrderStatus
from apps.orders.public_views import PRIVATE_HEADERS, TOKEN_PARAM, load_order
from apps.orders.serializers import PUBLIC_ITEMS
from apps.restaurants.services import check_password_strength

from .models import CustomerProfile
from .permissions import IsCustomer
from .serializers import (
    ClaimSerializer, CustomerLoginSerializer, CustomerOrderDetailSerializer, CustomerOrderSerializer, CustomerPasswordSerializer,
    CustomerRegisterSerializer, CustomerSerializer, CustomerUpdateSerializer, customer_payload,
)

BAD_LOGIN = "Invalid email or password."


class CustomerView(APIView):
    authentication_classes = [CsrfSessionAuthentication]
    permission_classes = [IsCustomer]


class RegisterView(APIView):
    authentication_classes = [CsrfSessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "customer_signup"

    @extend_schema(request=CustomerRegisterSerializer, responses={201: CustomerSerializer}, summary="Create a customer account")
    def post(self, request):
        enforce_csrf(request)
        data = CustomerRegisterSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        User = get_user_model()
        try:
            with transaction.atomic():
                user = User.objects.create_user(v["email"], v["password"], first_name=v["first_name"].strip(), last_name=v["last_name"].strip())
                check_password_strength(v["password"], user)  # with the user, so a password that is just their name or email is refused too
                CustomerProfile.objects.create(user=user, phone=v["phone"])
        except IntegrityError:
            raise ValidationError({"email": ["An account with this email already exists."]}) from None
        login(request, user)
        return Response(customer_payload(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    authentication_classes = [CsrfSessionAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [LoginIPThrottle, LoginEmailThrottle]

    @extend_schema(request=CustomerLoginSerializer, responses=CustomerSerializer, summary="Sign in to a customer account")
    def post(self, request):
        enforce_csrf(request)
        data = CustomerLoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(request, email=data.validated_data["email"], password=data.validated_data["password"])
        # One message for a wrong password, an unknown email, a closed account, and an email that belongs to a restaurant user.
        if user is None or not hasattr(user, "customer_profile"):
            raise AuthenticationFailed(BAD_LOGIN)
        login(request, user)
        return Response(customer_payload(user))


class LogoutView(CustomerView):
    @extend_schema(request=None, responses={204: None}, summary="Sign out")
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(CustomerView):
    @extend_schema(responses=CustomerSerializer, summary="Your account")
    def get(self, request):
        return Response(customer_payload(request.user))

    @extend_schema(request=CustomerUpdateSerializer, responses=CustomerSerializer, summary="Change your name or phone number")
    def patch(self, request):
        data = CustomerUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user, v = request.user, data.validated_data
        with transaction.atomic():
            for field in ("first_name", "last_name"):
                if field in v:
                    setattr(user, field, v[field].strip())
            user.save(update_fields=["first_name", "last_name"])
            if "phone" in v:
                user.customer_profile.phone = v["phone"]
                user.customer_profile.save(update_fields=["phone"])
        if not user.first_name:
            raise ValidationError({"first_name": ["Your first name can't be empty."]})
        return Response(customer_payload(user))


class PasswordView(CustomerView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_change"

    @extend_schema(request=CustomerPasswordSerializer, responses={204: None}, summary="Change your password")
    def post(self, request):
        data = CustomerPasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(data.validated_data["current_password"]):
            raise ValidationError({"current_password": ["Incorrect password."]})
        check_password_strength(data.validated_data["new_password"], user, field="new_password")
        user.set_password(data.validated_data["new_password"])
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)  # this device stays signed in; every other session ends
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrderListView(ListAPIView):
    """Your orders, newest first. `?active=1` for the ones still in progress."""

    authentication_classes = [CsrfSessionAuthentication]
    permission_classes = [IsCustomer]
    serializer_class = CustomerOrderSerializer
    pagination_class = DefaultCursorPagination

    def get_queryset(self):
        qs = Order.objects.filter(customer=self.request.user.customer_profile).select_related("restaurant").prefetch_related("items")
        if self.request.query_params.get("active") == "1":
            qs = qs.exclude(status__in=[OrderStatus.COMPLETED, OrderStatus.REJECTED, OrderStatus.CANCELLED])
        return qs.order_by("-id")


class OrderDetailView(CustomerView):
    @extend_schema(responses=CustomerOrderDetailSerializer, summary="One of your orders")
    def get(self, request, public_id):
        order = Order.objects.filter(customer=request.user.customer_profile, public_id=public_id).select_related("restaurant").first()
        if order is None:
            from rest_framework.exceptions import NotFound

            raise NotFound("Order not found.")
        return Response(CustomerOrderDetailSerializer(order, context={"request": request}).data, headers=PRIVATE_HEADERS)


class ClaimView(CustomerView):
    """Add an order you placed as a guest to your account, using its private link. Nothing else can link an order."""

    @extend_schema(request=ClaimSerializer, responses=CustomerOrderSerializer, summary="Add a guest order to your account")
    def post(self, request):
        data = ClaimSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = load_order(data.validated_data["token"])  # a wrong or revoked link is the usual 404
        profile = request.user.customer_profile
        with transaction.atomic():
            locked = Order.objects.select_for_update().select_related("restaurant").prefetch_related(PUBLIC_ITEMS).get(pk=order.pk)
            if locked.customer_id is None:
                locked.customer = profile
                locked.save(update_fields=["customer", "updated_at"])
            elif locked.customer_id != profile.pk:
                raise Conflict("This order already belongs to another account.", code="already_linked")
        return Response(CustomerOrderSerializer(locked).data)
