"""Restaurants (tenants) and the memberships that grant staff access to them.

Authorization for restaurant operations comes only from an active
RestaurantMembership, never from User.is_staff / is_superuser.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator, RegexValidator
from django.db import models

from .prefixes import unique_prefix
from .validators import (
    CURRENCY_PATTERN,
    ORDER_PREFIX_PATTERN,
    RESERVED_SLUGS,
    SLUG_PATTERN,
    validate_iana_timezone,
    validate_slug_not_reserved,
)


class MembershipRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    MANAGER = "MANAGER", "Manager"
    STAFF = "STAFF", "Staff"


class RestaurantCategory(models.TextChoices):
    """What kind of food a restaurant mainly serves. Used to filter the marketplace. Extend by adding values: no migration of data is needed."""

    AFRICAN = "AFRICAN", "African"
    FAST_FOOD = "FAST_FOOD", "Fast food"
    GRILL = "GRILL", "Grill and BBQ"
    BAKERY = "BAKERY", "Bakery and pastries"
    CAFE = "CAFE", "Cafe and drinks"
    PIZZA = "PIZZA", "Pizza"
    ASIAN = "ASIAN", "Asian"
    HEALTHY = "HEALTHY", "Healthy"
    OTHER = "OTHER", "Other"


def logo_path(instance, filename):
    return f"restaurants/{instance.pk}/logo/{filename}"


def cover_path(instance, filename):
    return f"restaurants/{instance.pk}/cover/{filename}"


class Restaurant(models.Model):
    name = models.CharField(max_length=120)
    slug = models.CharField(
        max_length=63,
        unique=True,
        validators=[
            MinLengthValidator(3),
            RegexValidator(SLUG_PATTERN, "Use lowercase letters, digits and single hyphens."),
            validate_slug_not_reserved,
        ],
        help_text="Public URL identifier. Lowercase letters, digits and hyphens.",
    )
    order_prefix = models.CharField(
        max_length=5, unique=True, null=True, blank=True,
        validators=[RegexValidator(ORDER_PREFIX_PATTERN, "Use 3 to 5 capital letters or digits, starting with a letter.")],
        help_text="This restaurant's own order ID prefix (the PRM in PRM-8K29P). Made automatically; locked once it has orders.",
    )
    description = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    logo = models.ImageField(upload_to=logo_path, max_length=200, null=True, blank=True, help_text="Shown at the top of the restaurant's page.")
    cover_image = models.ImageField(upload_to=cover_path, max_length=200, null=True, blank=True, help_text="The banner picture on the restaurant's page.")

    pickup_fee = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        help_text="A small extra charge added to every pickup order, in the restaurant's currency. 0 means no fee. Shown to the customer before they order.",
    )

    # Late pickup policy: the restaurant's own rules for customers who collect late. Off by default. A customer must see and accept it
    # before placing a pickup order; the rules are copied onto the order so a later change never alters an order already placed.
    late_fee_enabled = models.BooleanField(default=False)
    late_grace_minutes = models.PositiveSmallIntegerField(default=15, help_text="Free minutes after the order is ready (or after the chosen pickup time, if later).")
    late_fee_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="Charged for each full or part interval after the grace period.")
    late_fee_interval_minutes = models.PositiveSmallIntegerField(default=15)
    late_fee_max = models.DecimalField(max_digits=8, decimal_places=2, default=0, help_text="The most a single order can ever be charged.")

    # Marketplace profile. Coordinates are optional: a restaurant without them is still found by name, area and category,
    # just not by distance. Plain latitude/longitude keep the design extensible toward PostGIS (swap for a PointField later).
    category = models.CharField(max_length=20, choices=RestaurantCategory.choices, blank=True)
    area = models.CharField(max_length=120, blank=True, help_text="Neighbourhood, town or district customers search by, e.g. Akungba-Akoko.")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    listed_in_marketplace = models.BooleanField(default=False, help_text="Show this restaurant in the ServeFlow marketplace. Off until the owner switches it on.")
    marketplace_approved = models.BooleanField(
        default=False, editable=False,
        help_text="ServeFlow has checked this restaurant and allowed it into the marketplace. Only the platform owner sets it; the restaurant switch above does nothing until it is on.")
    # Maintained by the reviews feature from verified, completed orders only. Never typed in by hand.
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, editable=False)
    rating_count = models.PositiveIntegerField(default=0, editable=False)

    # is_active: platform-level switch (suspended restaurants are not public).
    # accepting_orders: operational switch staff can flip to pause new orders.
    is_active = models.BooleanField(default=True)
    accepting_orders = models.BooleanField(
        default=False,
        help_text="New restaurants do not take orders until this is switched on.",
    )
    auto_accept_orders = models.BooleanField(
        default=False,
        help_text="New orders are accepted the moment they arrive, so nobody has to press Accept in a rush. Preparing still waits for payment.",
    )

    # No defaults: these are per-restaurant facts and must be set deliberately.
    currency = models.CharField(
        max_length=3,
        validators=[RegexValidator(CURRENCY_PATTERN, "Use a 3-letter uppercase code, e.g. USD.")],
        help_text="ISO 4217 code. Format is validated; the code list is not.",
    )
    timezone = models.CharField(max_length=64, validators=[validate_iana_timezone])

    # Fulfilment options a customer may choose per order.
    pickup_enabled = models.BooleanField(default=True)
    dine_in_enabled = models.BooleanField(default=False)
    requires_table_number = models.BooleanField(
        default=False,
        help_text="Dine-in orders must include a table number. Requires dine-in.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(pickup_enabled=True) | models.Q(dine_in_enabled=True),
                name="restaurants_restaurant_fulfilment_enabled",
            ),
            models.CheckConstraint(
                condition=models.Q(requires_table_number=False) | models.Q(dine_in_enabled=True),
                name="restaurants_restaurant_table_requires_dine_in",
            ),
            models.CheckConstraint(
                condition=models.Q(slug__regex=SLUG_PATTERN),
                name="restaurants_restaurant_slug_format",
            ),
            models.CheckConstraint(
                condition=~models.Q(slug__in=RESERVED_SLUGS),
                name="restaurants_restaurant_slug_not_reserved",
            ),
            models.CheckConstraint(
                condition=models.Q(currency__regex=CURRENCY_PATTERN),
                name="restaurants_restaurant_currency_format",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(latitude__isnull=True, longitude__isnull=True)
                    | models.Q(latitude__isnull=False, longitude__isnull=False, latitude__gte=-90, latitude__lte=90,
                               longitude__gte=-180, longitude__lte=180)
                ),
                name="restaurants_restaurant_coordinates_valid",
            ),
            models.CheckConstraint(condition=models.Q(pickup_fee__gte=0), name="restaurants_restaurant_pickup_fee_non_negative"),
            models.CheckConstraint(
                condition=(models.Q(late_fee_enabled=False)
                           | models.Q(late_fee_amount__gt=0, late_fee_max__gte=models.F("late_fee_amount"),
                                      late_fee_interval_minutes__gte=5, late_fee_interval_minutes__lte=240)),
                name="restaurants_restaurant_late_policy_valid",
            ),
            models.CheckConstraint(condition=models.Q(late_grace_minutes__lte=240), name="restaurants_restaurant_late_grace_limit"),
            models.CheckConstraint(
                condition=models.Q(category="") | models.Q(category__in=RestaurantCategory.values),
                name="restaurants_restaurant_category_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(rating_average__isnull=True, rating_count=0)
                    | models.Q(rating_average__isnull=False, rating_count__gt=0, rating_average__gte=1, rating_average__lte=5)
                ),
                name="restaurants_restaurant_rating_consistent",
            ),
            models.CheckConstraint(
                condition=models.Q(order_prefix__isnull=True) | models.Q(order_prefix__regex=ORDER_PREFIX_PATTERN),
                name="restaurants_restaurant_order_prefix_format",
            ),
        ]
        indexes = [
            models.Index(fields=["latitude", "longitude"], name="restaurants_coordinates_idx"),
            models.Index(fields=["listed_in_marketplace", "is_active"], name="restaurants_listing_idx"),
        ]

    def save(self, *args, **kwargs):
        if not self.order_prefix:  # every creation path (API, owner dashboard, admin) gets one
            self.order_prefix = unique_prefix(
                self.name, lambda p: Restaurant.objects.filter(order_prefix=p).exclude(pk=self.pk).exists()
            )
            fields = kwargs.get("update_fields")
            if fields is not None:
                kwargs["update_fields"] = {*fields, "order_prefix"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class RestaurantMembership(models.Model):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name="memberships"
    )
    # PROTECT: accounts are deactivated, not deleted, so history stays intact.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="restaurant_memberships",
    )
    role = models.CharField(
        max_length=16, choices=MembershipRole.choices, default=MembershipRole.STAFF
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "user"],
                name="restaurants_membership_unique_user_per_restaurant",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=MembershipRole.values),
                name="restaurants_membership_role_valid",
            ),
        ]

    def __str__(self):
        return f"{self.user} @ {self.restaurant} ({self.role})"

    def clean(self):
        super().clean()
        # Last-owner rule. This validation covers forms and admin only; it is not
        # race-safe and is bypassed by queryset.update(). The member-management
        # service (later stage) must enforce it again under a row lock.
        if not self.pk or not self.restaurant_id:
            return
        previous = (
            RestaurantMembership.objects.filter(pk=self.pk).values("role", "is_active").first()
        )
        if not previous or previous["role"] != MembershipRole.OWNER or not previous["is_active"]:
            return
        if self.role == MembershipRole.OWNER and self.is_active:
            return
        other_active_owner = (
            RestaurantMembership.objects.filter(
                restaurant_id=self.restaurant_id,
                role=MembershipRole.OWNER,
                is_active=True,
            )
            .exclude(pk=self.pk)
            .exists()
        )
        if not other_active_owner:
            raise ValidationError("A restaurant must keep at least one active owner.")


class OpeningPeriod(models.Model):
    """One stretch of opening time on one weekday, in the restaurant's own timezone (Monday is 0). A day may have several
    (lunch and dinner). A period can't cross midnight: a late night is two periods, e.g. 18:00-23:59 and 00:00-02:00 the next day.
    A restaurant with no periods at all is treated as having no published hours, not as closed."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="opening_periods")
    weekday = models.PositiveSmallIntegerField()
    opens = models.TimeField()
    closes = models.TimeField()

    class Meta:
        ordering = ["weekday", "opens"]
        constraints = [
            models.CheckConstraint(condition=models.Q(weekday__gte=0, weekday__lte=6), name="restaurants_period_weekday_valid"),
            models.CheckConstraint(condition=models.Q(closes__gt=models.F("opens")), name="restaurants_period_closes_after_opens"),
            models.UniqueConstraint(fields=["restaurant", "weekday", "opens"], name="restaurants_period_unique_start"),
        ]

    def __str__(self):
        return f"{self.restaurant.slug} day {self.weekday} {self.opens:%H:%M}-{self.closes:%H:%M}"


class PaymentAccount(models.Model):
    """Where customers send their payment for an order (the restaurant's own bank account). Customers pay before the
    restaurant starts preparing anything, so a restaurant can't take orders until this is filled in. ServeFlow never
    holds the money: this is only the account the restaurant wants customers to pay into."""

    restaurant = models.OneToOneField(Restaurant, on_delete=models.CASCADE, related_name="payment_account")
    bank_name = models.CharField(max_length=80)
    account_name = models.CharField(max_length=120)
    account_number = models.CharField(max_length=34)
    instructions = models.CharField(max_length=300, blank=True, help_text="Anything the customer should know, e.g. which narration to use.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.restaurant.slug}: {self.bank_name}"

    @property
    def ready(self):
        return bool(self.bank_name and self.account_name and self.account_number)


class PushSubscription(models.Model):
    """One device a staff member turned order alerts on for. The browser gives us an address (`endpoint`) and two keys; we use
    them to send a small encrypted message when an order arrives. Removed when the person turns alerts off, or when the
    browser tells us the device no longer exists."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name="push_subscriptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.TextField(unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_success_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.restaurant.slug}: {self.user_id} ({self.endpoint[:40]})"
