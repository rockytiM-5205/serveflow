"""Platform-level business data: plans, subscriptions, subscription payments, API credentials, usage, audit.

Everything here belongs to ServeFlow itself, not to a restaurant. Subscription payments (what a restaurant pays
ServeFlow) are kept apart from orders.Payment (what a diner pays a restaurant).
"""
from django.conf import settings
from django.db import models

from apps.restaurants.models import Restaurant


class Plan(models.Model):
    class Interval(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        YEARLY = "YEARLY", "Yearly"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"

    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=300, blank=True)
    interval = models.CharField(max_length=10, choices=Interval.choices)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    included_orders = models.PositiveIntegerField(default=300, help_text="Completed orders included in each billing period. This is the billable metric.")
    included_requests = models.PositiveBigIntegerField(help_text="Technical monthly cap on API requests per key (abuse protection, not billing).")
    rate_limit_per_minute = models.PositiveIntegerField()
    pack_orders = models.PositiveIntegerField(null=True, blank=True, help_text="Size of the extra order pack this plan can buy. Empty means no packs.")
    pack_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Price of one order pack, in the plan's currency.")
    features = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    is_trial = models.BooleanField(default=False, editable=False, help_text="The built-in free plan every new restaurant starts on. Not for sale.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["is_trial"], condition=models.Q(is_trial=True), name="platform_single_trial_plan"),
            models.CheckConstraint(condition=models.Q(price__gte=0), name="platform_plan_price_non_negative"),
            models.CheckConstraint(condition=models.Q(rate_limit_per_minute__gte=1), name="platform_plan_rate_limit_positive"),
            models.CheckConstraint(
                condition=(models.Q(pack_orders__isnull=True, pack_price__isnull=True)
                           | models.Q(pack_orders__gt=0, pack_price__gt=0)),
                name="platform_plan_pack_offer_complete",
            ),
        ]

    def __str__(self):
        return self.name


class Subscription(models.Model):
    """One current subscription per restaurant. A trial is a subscription in TRIAL status with its own period."""

    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Trial"
        ACTIVE = "ACTIVE", "Active"
        PAST_DUE = "PAST_DUE", "Past due"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    restaurant = models.OneToOneField(Restaurant, on_delete=models.PROTECT, related_name="subscription")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions", help_text="What they're on now: the free trial plan, then a paid plan once a payment is confirmed.")
    next_plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="chosen_by", help_text="The paid plan they intend to pay for.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIAL)
    started_at = models.DateTimeField()
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()
    billing_anchor = models.DateTimeField(null=True, blank=True, help_text="When the paid subscription first began. Every later period starts on this day of the month (or the last day of a shorter month).")
    pending_plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="downgrading", help_text="A cheaper plan that takes effect at the next billing anniversary.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "current_period_end"], name="platform_sub_status_end_idx")]

    def __str__(self):
        return f"{self.restaurant.slug}: {self.status}"


class SubscriptionPayment(models.Model):
    class Status(models.TextChoices):
        AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION", "Awaiting confirmation"
        CONFIRMED = "CONFIRMED", "Confirmed"
        FAILED = "FAILED", "Failed"

    class Provider(models.TextChoices):
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        GATEWAY = "GATEWAY", "Payment gateway"

    class Kind(models.TextChoices):
        SUBSCRIPTION = "SUBSCRIPTION", "Subscription"
        ORDER_PACK = "ORDER_PACK", "Order pack"
        UPGRADE = "UPGRADE", "Plan upgrade"

    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="payments")
    reference = models.CharField(max_length=64, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.AWAITING_CONFIRMATION)
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.BANK_TRANSFER)
    kind = models.CharField(max_length=14, choices=Kind.choices, default=Kind.SUBSCRIPTION, help_text="What this money buys. Never mixed with food-order payments (orders.Payment).")
    order_pack = models.OneToOneField("platform_admin.OrderPack", null=True, blank=True, on_delete=models.PROTECT, related_name="payment")
    plan_change = models.OneToOneField("platform_admin.PlanChange", null=True, blank=True, on_delete=models.PROTECT, related_name="payment")
    provider_reference = models.CharField(max_length=100, blank=True, help_text="The payment provider's own transaction id, when one confirmed it.")
    failure_reason = models.CharField(max_length=200, blank=True)
    transacted_at = models.DateTimeField()
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="platform_payment_amount_positive"),
            models.CheckConstraint(condition=models.Q(kind__in=["SUBSCRIPTION", "ORDER_PACK", "UPGRADE"]), name="platform_payment_kind_valid"),
            models.CheckConstraint(
                condition=(models.Q(kind="ORDER_PACK", order_pack__isnull=False)
                           | (~models.Q(kind="ORDER_PACK") & models.Q(order_pack__isnull=True))),
                name="platform_payment_pack_matches_kind",
            ),
            models.CheckConstraint(
                condition=(models.Q(kind="UPGRADE", plan_change__isnull=False)
                           | (~models.Q(kind="UPGRADE") & models.Q(plan_change__isnull=True))),
                name="platform_payment_change_matches_kind",
            ),
            models.UniqueConstraint(
                fields=["provider", "provider_reference"], condition=~models.Q(provider_reference=""),
                name="platform_payment_provider_reference_unique",
            ),
        ]

    def __str__(self):
        return self.reference


class ApiCredential(models.Model):
    """Only a SHA-256 hash of the secret is stored. `prefix` (the first characters) identifies the key and is not secret."""

    class Environment(models.TextChoices):
        LIVE = "live", "Live"
        TEST = "test", "Test"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="api_credentials")
    name = models.CharField(max_length=60)
    environment = models.CharField(max_length=4, choices=Environment.choices)
    prefix = models.CharField(max_length=16, unique=True)
    secret_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    rate_limit_per_minute = models.PositiveIntegerField(null=True, blank=True)
    monthly_request_limit = models.PositiveBigIntegerField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    def __str__(self):
        return self.prefix


class ApiUsageDaily(models.Model):
    """Request counts per restaurant, day, method and path. Written by `services.record_usage`."""

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="+")
    date = models.DateField()
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=200, help_text="Route pattern such as /api/v1/restaurants/<slug>/menu/, never a raw URL.")
    requests = models.PositiveBigIntegerField(default=0)
    errors = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["restaurant", "date", "method", "path"], name="platform_usage_unique_day_route")]
        indexes = [models.Index(fields=["date"], name="platform_usage_date_idx")]


class RateLimitEvent(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="+")
    credential = models.ForeignKey(ApiCredential, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    endpoint = models.CharField(max_length=200)
    limit = models.CharField(max_length=40, help_text="For example 60/min.")
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["-occurred_at"], name="platform_ratelimit_recent_idx")]


class PlatformAuditEvent(models.Model):
    """Append-only record of owner and platform actions. Keep `summary` free of secrets and personal details."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=64)
    resource_type = models.CharField(max_length=64)
    resource_id = models.CharField(max_length=64, blank=True)
    summary = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["-created_at"], name="platform_audit_recent_idx")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit events can't be deleted.")

    def __str__(self):
        return f"{self.action} {self.resource_type}#{self.resource_id}"


class PaymentDetails(models.Model):
    """Where restaurants send subscription payments (bank transfer). One row, edited by the platform owner only.
    The account number is shown to signed-in restaurant owners, never on the public pricing page."""

    bank_name = models.CharField(max_length=100, blank=True)
    account_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    instructions = models.CharField(max_length=500, blank=True, help_text="Shown publicly, so never put account details here.")
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def ready(self):
        return bool(self.bank_name and self.account_number)

    def __str__(self):
        return "Payment details"


class ApiCredentialMonthlyUsage(models.Model):
    """Requests made with one API key in one calendar month; checked against the key's monthly allowance."""

    credential = models.ForeignKey(ApiCredential, on_delete=models.CASCADE, related_name="monthly_usage")
    month = models.DateField(help_text="First day of the month.")
    requests = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["credential", "month"], name="platform_key_usage_unique_month")]


class PlatformNotification(models.Model):
    """Something the platform owner should know about (a transfer to confirm, a signup, a trial ending, a lock).
    `dedupe_key` makes each event notify once however many times the code that raises it runs."""

    kind = models.CharField(max_length=32)
    title = models.CharField(max_length=120)
    detail = models.CharField(max_length=255, blank=True)
    link = models.CharField(max_length=120, blank=True, help_text="An in-app route such as #/payments.")
    restaurant = models.ForeignKey(Restaurant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    dedupe_key = models.CharField(max_length=80, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["-created_at"], name="platform_notif_recent_idx")]

    def __str__(self):
        return self.title


class BillingPeriod(models.Model):
    """One billing period of a subscription, with the plan's terms frozen at the moment it opened.

    Editing a plan later never changes an existing period. `ends_at` is exclusive: the next period starts exactly then,
    which is when usage resets (a period that runs Nov 12 to Dec 11 has ends_at = Dec 12 00:00 in the anchor's time of day).
    """

    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="periods")
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="+")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="+")
    plan_name = models.CharField(max_length=60)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    included_orders = models.PositiveIntegerField(help_text="Snapshot of the plan's completed-order allowance for this period.")
    rate_limit_per_minute = models.PositiveIntegerField(help_text="Snapshot of the plan's API rate limit.")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_at"]
        constraints = [
            models.UniqueConstraint(fields=["subscription", "starts_at"], name="platform_period_unique_start"),
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="platform_period_ends_after_start"),
        ]
        indexes = [models.Index(fields=["restaurant", "-starts_at"], name="platform_period_restaurant_idx")]

    def __str__(self):
        return f"{self.restaurant.slug} {self.starts_at:%Y-%m-%d} - {self.ends_at:%Y-%m-%d}"


class OrderPack(models.Model):
    """Extra completed-order capacity bought for ONE billing period. It only counts once payment is confirmed, expires with
    the period (never rolls over) and is never renewed automatically."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Awaiting payment"
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        FAILED = "FAILED", "Failed"

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="order_packs")
    billing_period = models.ForeignKey(BillingPeriod, on_delete=models.PROTECT, related_name="order_packs")
    orders = models.PositiveIntegerField(help_text="Completed orders this pack adds.")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    reference = models.CharField(max_length=64, unique=True, help_text="Unique purchase and payment reference.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(orders__gt=0), name="platform_pack_orders_positive"),
            models.CheckConstraint(condition=models.Q(status__in=["PENDING", "ACTIVE", "EXPIRED", "FAILED"]), name="platform_pack_status_valid"),
        ]

    def __str__(self):
        return self.reference


class OrderUsage(models.Model):
    """The usage ledger: one row each time an order becomes billable (COMPLETED). Rows are never edited or deleted, so a
    refund, a later plan change or a renewal cannot rewrite history. The unique constraint makes double counting impossible."""

    class Event(models.TextChoices):
        ORDER_COMPLETED = "ORDER_COMPLETED", "Order completed"

    class ChargedTo(models.TextChoices):
        PLAN = "PLAN", "Plan allowance"
        PACK = "PACK", "Order pack"
        OVERAGE = "OVERAGE", "Over allowance"  # an order accepted earlier and completed after the allowance ran out

    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="+")
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="+")
    billing_period = models.ForeignKey(BillingPeriod, on_delete=models.PROTECT, related_name="usage")
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="usage_records")
    event_type = models.CharField(max_length=20, choices=Event.choices, default=Event.ORDER_COMPLETED)
    charged_to = models.CharField(max_length=8, choices=ChargedTo.choices)
    order_pack = models.ForeignKey(OrderPack, null=True, blank=True, on_delete=models.PROTECT, related_name="usage")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "event_type"], name="platform_usage_one_row_per_order_event"),
            models.CheckConstraint(condition=models.Q(charged_to__in=["PLAN", "PACK", "OVERAGE"]), name="platform_usage_charged_to_valid"),
            models.CheckConstraint(
                condition=(models.Q(charged_to="PACK", order_pack__isnull=False) | (~models.Q(charged_to="PACK") & models.Q(order_pack__isnull=True))),
                name="platform_usage_pack_matches_charge",
            ),
        ]
        indexes = [models.Index(fields=["billing_period", "charged_to"], name="platform_usage_period_idx")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Usage records are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Usage records can't be deleted.")


class PlanChange(models.Model):
    """An upgrade or downgrade of a paying subscription, kept as a record.

    UPGRADE: takes effect immediately once its payment (the price difference) is confirmed; the current period's allowance
    becomes the new plan's allowance, and usage already recorded stays. DOWNGRADE: takes effect when the next billing
    period opens (`effective_at` is the current period's end); nothing changes in the running period.
    """

    class Kind(models.TextChoices):
        UPGRADE = "UPGRADE", "Upgrade"
        DOWNGRADE = "DOWNGRADE", "Downgrade"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPLIED = "APPLIED", "Applied"
        CANCELLED = "CANCELLED", "Cancelled"

    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="plan_changes")
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="+")
    from_plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="+")
    to_plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    billing_period = models.ForeignKey(BillingPeriod, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    effective_at = models.DateTimeField(null=True, blank=True)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Upgrade only: the price difference, no time proration.")
    allowance_before = models.PositiveIntegerField(null=True, blank=True)
    allowance_after = models.PositiveIntegerField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["subscription"], condition=models.Q(status="PENDING"), name="platform_planchange_one_pending"),
            models.CheckConstraint(condition=models.Q(kind__in=["UPGRADE", "DOWNGRADE"]), name="platform_planchange_kind_valid"),
            models.CheckConstraint(condition=models.Q(status__in=["PENDING", "APPLIED", "CANCELLED"]), name="platform_planchange_status_valid"),
        ]


class PaymentWebhookEvent(models.Model):
    """Every provider notification we received, once. The unique (provider, event_id) pair makes processing idempotent: a
    provider retrying the same event is recognised and does nothing. The raw body is not stored, only its hash."""

    provider = models.CharField(max_length=20)
    event_id = models.CharField(max_length=100)
    payload_sha256 = models.CharField(max_length=64)
    reference = models.CharField(max_length=64, blank=True)
    reported_status = models.CharField(max_length=16, blank=True)
    outcome = models.CharField(max_length=40, blank=True)
    payment = models.ForeignKey(SubscriptionPayment, null=True, blank=True, on_delete=models.PROTECT, related_name="webhook_events")
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "event_id"], name="platform_webhook_event_unique")]
