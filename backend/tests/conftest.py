import itertools

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.restaurants.models import MembershipRole, Restaurant, RestaurantMembership

_counter = itertools.count(1)
PASSWORD = "s3cret-pass-123"


@pytest.fixture(autouse=True)
def _clear_cache():
    """Throttle counters live in the cache; keep tests independent."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def csrf_client():
    """A client that enforces CSRF like a real browser."""
    return APIClient(enforce_csrf_checks=True)


@pytest.fixture
def make_user(db):
    def _make(**kwargs):
        n = next(_counter)
        kwargs.setdefault("email", f"user{n}@example.com")
        kwargs.setdefault("password", PASSWORD)
        return get_user_model().objects.create_user(**kwargs)

    return _make


@pytest.fixture
def make_restaurant(db):
    def _make(**kwargs):
        n = next(_counter)
        kwargs.setdefault("name", f"Restaurant {n}")
        kwargs.setdefault("slug", f"restaurant-{n}")
        kwargs.setdefault("currency", "USD")
        kwargs.setdefault("timezone", "UTC")
        with_account = kwargs.pop("with_account", True)  # customers pay first, so a restaurant needs somewhere to pay
        restaurant = Restaurant.objects.create(**kwargs)
        if with_account:
            from apps.restaurants.models import PaymentAccount

            PaymentAccount.objects.create(restaurant=restaurant, bank_name="Test Bank", account_name="Test Kitchen", account_number="0123456789")
        return restaurant

    return _make


@pytest.fixture
def make_membership(db):
    def _make(restaurant, user, role=MembershipRole.STAFF, **kwargs):
        return RestaurantMembership.objects.create(restaurant=restaurant, user=user, role=role, **kwargs)

    return _make


@pytest.fixture
def make_category(db):
    from apps.menu.models import MenuCategory

    def _make(restaurant, **kwargs):
        n = next(_counter)
        kwargs.setdefault("name", f"Category {n}")
        return MenuCategory.objects.create(restaurant=restaurant, **kwargs)

    return _make


@pytest.fixture
def make_item(db):
    from apps.menu.models import MenuItem

    def _make(category, **kwargs):
        n = next(_counter)
        kwargs.setdefault("name", f"Item {n}")
        kwargs.setdefault("price", "5.00")
        return MenuItem.objects.create(restaurant=category.restaurant, category=category, **kwargs)

    return _make


@pytest.fixture
def staff_login(api_client, make_user, make_membership):
    """Sign a new user in with the given role in the given restaurant."""

    def _login(restaurant, role=MembershipRole.MANAGER):
        user = make_user()
        make_membership(restaurant, user, role)
        api_client.force_login(user)
        return user

    return _login


@pytest.fixture
def shop(make_restaurant, make_category, make_item):
    """A restaurant that is open for orders (pickup and dine-in) with two items."""
    from types import SimpleNamespace

    restaurant = make_restaurant(accepting_orders=True, dine_in_enabled=True)
    category = make_category(restaurant)
    return SimpleNamespace(
        restaurant=restaurant,
        category=category,
        rice=make_item(category, name="Rice", price="2.50", unit_name="spoon"),
        beans=make_item(category, name="Beans", price="1.25"),
    )


@pytest.fixture
def place(api_client):
    """Place a guest order. items is a list of (menu_item_id, quantity)."""
    import uuid

    from django.urls import reverse

    def _place(restaurant, items, key=None, phone="+442079460958", **extra):
        from datetime import timedelta

        from django.utils import timezone

        body = {
            "customer_name": "Ada", "customer_phone": phone, "fulfilment_type": "PICKUP",
            "pickup_at": (timezone.now() + timedelta(hours=2)).isoformat(),  # pickup needs a time, at least 30 minutes ahead
            "items": [{"menu_item_id": item_id, "quantity": quantity} for item_id, quantity in items], **extra,
        }
        return api_client.post(
            reverse("public-order-create", kwargs={"slug": restaurant.slug}), body, format="json",
            HTTP_IDEMPOTENCY_KEY=key or uuid.uuid4().hex,
        )

    return _place


@pytest.fixture
def order_in(shop, place):
    """An existing order (rice x2 = 5.00) moved straight to the given status."""
    from apps.orders.models import Order

    def _make(status="PENDING", **kwargs):
        response = place(shop.restaurant, [(shop.rice.pk, 2)], **kwargs)
        assert response.status_code == 201, response.content
        order = Order.objects.order_by("-id").first()
        if status != "PENDING":
            Order.objects.filter(pk=order.pk).update(status=status)
            order.refresh_from_db()
        return order

    return _make
