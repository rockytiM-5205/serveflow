"""Business rules for the owner API. Views stay thin; every state change happens here, inside a transaction,
with an audit event."""
import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.common.exceptions import Conflict
from apps.restaurants.models import Restaurant

from . import locks, usage
from .models import (
    ApiCredential, ApiUsageDaily, BillingPeriod, OrderPack, Plan, PlanChange, PlatformAuditEvent, RateLimitEvent, Subscription,
    SubscriptionPayment,
)
from .notifications import notify


def trial_days():
    return getattr(settings, "BILLING_TRIAL_DAYS", 2)


def grace_days():
    return getattr(settings, "BILLING_GRACE_DAYS", 3)


def audit(actor, action, resource_type, resource_id="", summary=""):
    return PlatformAuditEvent.objects.create(
        actor=actor, action=action, resource_type=resource_type, resource_id=str(resource_id), summary=summary[:255]
    )


# ---------- customers ----------
def set_restaurant_active(restaurant_id, active, actor):
    with transaction.atomic():
        restaurant = get_object_or_404(Restaurant.objects.select_for_update(), pk=restaurant_id)
        if restaurant.is_active == active:
            raise Conflict(
                "This restaurant is already active." if active else "This restaurant is already suspended.",
                code="not_suspended" if active else "already_suspended",
            )
        restaurant.is_active = active
        restaurant.save(update_fields=["is_active", "updated_at"])
        audit(actor, "customer.reactivated" if active else "customer.suspended", "restaurant", restaurant.pk, restaurant.slug)
    return restaurant


# ---------- plans ----------
def archive_plan(plan_id, actor):
    with transaction.atomic():
        plan = get_object_or_404(Plan.objects.select_for_update(), pk=plan_id)
        if plan.is_trial:
            raise Conflict("The free trial plan is built in and can't be archived.", code="trial_plan")
        if plan.status == Plan.Status.ARCHIVED:
            raise Conflict("This plan is already archived.", code="already_archived")
        plan.status = Plan.Status.ARCHIVED
        plan.save(update_fields=["status", "updated_at"])
        audit(actor, "plan.archived", "plan", plan.pk, plan.name)
    return plan


# ---------- subscriptions ----------
def trial_plan():
    """The built-in free plan every new restaurant starts on (created on first use). Its request limits are only starting
    values: the owner edits them in Plans & Pricing like any other plan."""
    plan = Plan.objects.filter(is_trial=True).first()
    if plan is None:
        plan = Plan.objects.create(
            is_trial=True, name="Free trial", description="Included for every new restaurant while it tries ServeFlow.", interval=Plan.Interval.MONTHLY,
            price=Decimal("0.00"), currency="NGN", included_orders=30, included_requests=5000, rate_limit_per_minute=30, features=[])
    return plan


def start_trial(restaurant, plan=None, actor=None, days=None):
    """Start the free trial. Every trial runs on the built-in Free trial plan; `plan` is the PAID plan the restaurant intends to
    buy (optional, they can choose later)."""
    if plan is not None and (plan.is_trial or plan.status != Plan.Status.ACTIVE):
        raise Conflict("That plan isn't available.", code="plan_archived")
    with transaction.atomic():
        if Subscription.objects.filter(restaurant=restaurant).exists():
            raise Conflict("This restaurant already has a subscription.", code="subscription_exists")
        now = timezone.now()
        end = now + timedelta(days=days or trial_days())
        subscription = Subscription.objects.create(
            restaurant=restaurant, plan=trial_plan(), next_plan=plan, status=Subscription.Status.TRIAL, started_at=now,
            trial_ends_at=end, current_period_start=now, current_period_end=end,
        )
        usage.open_period(subscription, subscription.plan, now, end)
        audit(actor, "subscription.trial_started", "subscription", subscription.pk, f"{restaurant.slug} on the free trial" + (f", intends {plan.name}" if plan else ""))
    return subscription


def sync_lifecycle(now=None):
    """Bring stored statuses in line with the dates. A trial that has ended becomes EXPIRED at once (no grace). A paid
    subscription past its period end becomes PAST_DUE, then EXPIRED after BILLING_GRACE_DAYS. Locking does not wait for
    this (see locks.is_locked); this keeps the owner's lists accurate and raises the owner's notifications (a trial about to
    end, a restaurant that has just been locked), each once. Safe to run often. Returns what moved."""
    now = now or timezone.now()
    grace = timedelta(days=grace_days())
    with transaction.atomic():
        ending = Subscription.objects.filter(status=Subscription.Status.TRIAL, current_period_end__gt=now,
                                             current_period_end__lte=now + timedelta(hours=24)).select_related("restaurant")
        for sub in ending:
            notify("trial_ending", f"{sub.restaurant.name}'s trial ends soon", "Less than 24 hours left. They need to pay to keep working.",
                   f"#/customers?search={sub.restaurant.slug}", sub.restaurant, f"trial_ending:{sub.pk}:{sub.current_period_end:%Y%m%d}")
        trial_qs = Subscription.objects.filter(status=Subscription.Status.TRIAL, current_period_end__lt=now)
        lapsed_qs = Subscription.objects.filter(status__in=[Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE], current_period_end__lt=now - grace)
        locking = list((trial_qs | lapsed_qs).select_related("restaurant"))
        trials = trial_qs.update(status=Subscription.Status.EXPIRED, updated_at=now)
        lapsed = lapsed_qs.update(status=Subscription.Status.EXPIRED, updated_at=now)
        past_due = Subscription.objects.filter(status=Subscription.Status.ACTIVE, current_period_end__lt=now).update(
            status=Subscription.Status.PAST_DUE, updated_at=now)
        for sub in locking:
            notify("expired", f"{sub.restaurant.name} has been locked", "Their subscription ended without payment.",
                   f"#/customers?search={sub.restaurant.slug}", sub.restaurant, f"expired:{sub.pk}:{sub.current_period_end:%Y%m%d%H%M}")
        expired = trials + lapsed
        usage.expire_packs(now)
        apply_due_plan_changes(now)
        if expired or past_due:
            audit(None, "subscriptions.synced", "subscription", "", f"{past_due} past due, {expired} expired")
    return {"past_due": past_due, "expired": expired}


def _mark_confirmed(payment, actor, now, provider_name=None, provider_reference=""):
    payment.status = SubscriptionPayment.Status.CONFIRMED
    payment.confirmed_by = actor
    payment.confirmed_at = now
    fields = ["status", "confirmed_by", "confirmed_at"]
    if provider_name:
        payment.provider, payment.provider_reference = provider_name, provider_reference
        fields += ["provider", "provider_reference"]
    payment.save(update_fields=fields)


def _wrong_amount(expected, currency):
    return Conflict(
        f"The payment must equal {expected} {currency}.", code="amount_mismatch",
        details={"expected": str(expected), "currency": currency},
    )


def confirm_payment(payment_id, actor, *, provider_name=None, provider_reference=""):
    """A payment is verified server-side (the owner confirming a bank transfer, or a signed provider webhook) and only then
    does it do anything. What it does depends on its kind: SUBSCRIPTION opens the next billing period, ORDER_PACK activates
    the pack, UPGRADE applies the plan change. The browser never decides what is paid, and a payment is confirmed once."""
    with transaction.atomic():
        payment = get_object_or_404(SubscriptionPayment.objects.select_for_update(), pk=payment_id)
        if payment.status != SubscriptionPayment.Status.AWAITING_CONFIRMATION:
            raise Conflict("This payment isn't awaiting confirmation.", code="not_awaiting_confirmation")
        subscription = Subscription.objects.select_for_update(of=("self",)).select_related("plan", "restaurant").get(pk=payment.subscription_id)
        now = timezone.now()
        if payment.kind == SubscriptionPayment.Kind.ORDER_PACK:
            _confirm_pack(payment, subscription, actor, now, provider_name, provider_reference)
        elif payment.kind == SubscriptionPayment.Kind.UPGRADE:
            _confirm_upgrade(payment, subscription, actor, now, provider_name, provider_reference)
        else:
            _confirm_subscription(payment, subscription, actor, now, provider_name, provider_reference)
    locks.forget(subscription.restaurant.slug)  # a paid restaurant is unlocked right away
    return payment


def _confirm_subscription(payment, subscription, actor, now, provider_name, provider_reference):
    plan = subscription.next_plan or subscription.pending_plan or subscription.plan  # what this payment buys
    if plan.is_trial:
        raise Conflict("The restaurant hasn't chosen a paid plan yet.", code="no_plan_chosen")
    if subscription.status == Subscription.Status.CANCELLED:
        raise Conflict("The subscription is cancelled.", code="subscription_cancelled")
    if payment.currency != plan.currency or payment.amount != plan.price:
        raise _wrong_amount(plan.price, plan.currency)
    _mark_confirmed(payment, actor, now, provider_name, provider_reference)
    # Renewing early continues from the current period's end on the same anniversary day; paying first time or after a
    # lapse starts a fresh period now (see usage.start_paid_period). Each period freezes the plan's terms.
    period = usage.start_paid_period(subscription, plan, now)
    subscription.status = Subscription.Status.ACTIVE
    deferred = period.starts_at > now and plan.pk == subscription.pending_plan_id and plan.pk != subscription.plan_id
    if deferred:
        # A paid-ahead downgrade: the running period keeps its plan; sync_lifecycle moves the subscription at the anniversary.
        subscription.next_plan = None
    else:
        subscription.plan, subscription.next_plan = plan, None  # now on the paid plan
        if subscription.pending_plan_id == plan.pk:
            subscription.pending_plan = None
            PlanChange.objects.filter(subscription=subscription, status=PlanChange.Status.PENDING, kind=PlanChange.Kind.DOWNGRADE).update(
                status=PlanChange.Status.APPLIED, applied_at=now, effective_at=period.starts_at)
    subscription.save(update_fields=["current_period_start", "current_period_end", "billing_anchor", "status", "plan", "next_plan", "pending_plan", "updated_at"])
    audit(actor, "payment.confirmed", "payment", payment.pk, f"{payment.reference} for {subscription.restaurant.slug}, period {period.starts_at:%Y-%m-%d} to {period.ends_at:%Y-%m-%d}")


def _confirm_pack(payment, subscription, actor, now, provider_name, provider_reference):
    pack = OrderPack.objects.select_for_update().select_related("billing_period").get(pk=payment.order_pack_id)
    if pack.status != OrderPack.Status.PENDING:
        raise Conflict("This order pack isn't awaiting payment.", code="pack_not_pending")
    if payment.currency != pack.currency or payment.amount != pack.price:
        raise _wrong_amount(pack.price, pack.currency)
    _mark_confirmed(payment, actor, now, provider_name, provider_reference)
    if now >= pack.billing_period.ends_at:
        # The money arrived after the period it was bought for had ended. A pack never rolls over, so it can't be used.
        pack.status = OrderPack.Status.EXPIRED
        pack.save(update_fields=["status"])
        audit(actor, "order_pack.expired_unused", "order_pack", pack.pk, f"{pack.reference} paid after its billing period ended; refund or re-issue manually")
        notify("pack_expired", f"{subscription.restaurant.name}'s order pack arrived too late",
               f"{pack.reference} was paid after its period ended, so it adds no capacity. Refund or re-issue it.", "#/payments", subscription.restaurant, f"pack_expired:{pack.pk}")
        return
    pack.status, pack.activated_at = OrderPack.Status.ACTIVE, now
    pack.save(update_fields=["status", "activated_at"])
    audit(actor, "order_pack.activated", "order_pack", pack.pk, f"{pack.reference}: +{pack.orders} orders for {subscription.restaurant.slug}")


def _confirm_upgrade(payment, subscription, actor, now, provider_name, provider_reference):
    change = PlanChange.objects.select_for_update().select_related("to_plan").get(pk=payment.plan_change_id)
    if change.status != PlanChange.Status.PENDING:
        raise Conflict("This plan change is no longer pending.", code="change_not_pending")
    if subscription.status != Subscription.Status.ACTIVE:
        raise Conflict("The subscription must be active to apply an upgrade.", code="subscription_not_active")
    period = usage.current_period(subscription, now)
    if period is None or now >= period.ends_at:
        raise Conflict("There is no running billing period to upgrade.", code="no_active_billing_period")
    to_plan = change.to_plan
    if payment.currency != to_plan.currency or payment.amount != change.amount_due:
        raise _wrong_amount(change.amount_due, to_plan.currency)
    _mark_confirmed(payment, actor, now, provider_name, provider_reference)
    # The new terms apply to the running period from now on. Usage already recorded stays; the allowance never goes down.
    change.allowance_before = period.included_orders
    period.plan, period.plan_name, period.price = to_plan, to_plan.name, to_plan.price
    period.included_orders = max(period.included_orders, to_plan.included_orders)
    period.rate_limit_per_minute = to_plan.rate_limit_per_minute
    period.save(update_fields=["plan", "plan_name", "price", "included_orders", "rate_limit_per_minute"])
    change.status, change.applied_at, change.effective_at = PlanChange.Status.APPLIED, now, now
    change.billing_period, change.allowance_after = period, period.included_orders
    change.save(update_fields=["status", "applied_at", "effective_at", "billing_period", "allowance_before", "allowance_after"])
    subscription.plan = to_plan
    subscription.save(update_fields=["plan", "updated_at"])
    audit(actor, "subscription.upgraded", "subscription", subscription.pk,
          f"{subscription.restaurant.slug}: {change.from_plan.name} to {to_plan.name}, allowance {change.allowance_before} to {change.allowance_after}")


def fail_payment(payment_id, actor, reason):
    """Mark a pending payment as failed (never arrived, wrong amount, declined). Its pack or upgrade is cancelled."""
    reason = (reason or "").strip()[:200]
    if not reason:
        raise Conflict("Give a reason.", code="reason_required")
    with transaction.atomic():
        payment = get_object_or_404(SubscriptionPayment.objects.select_for_update().select_related("subscription__restaurant"), pk=payment_id)
        if payment.status != SubscriptionPayment.Status.AWAITING_CONFIRMATION:
            raise Conflict("This payment isn't awaiting confirmation.", code="not_awaiting_confirmation")
        payment.status, payment.failure_reason = SubscriptionPayment.Status.FAILED, reason
        payment.save(update_fields=["status", "failure_reason"])
        if payment.order_pack_id:
            OrderPack.objects.filter(pk=payment.order_pack_id, status=OrderPack.Status.PENDING).update(status=OrderPack.Status.FAILED)
        if payment.plan_change_id:
            PlanChange.objects.filter(pk=payment.plan_change_id, status=PlanChange.Status.PENDING).update(status=PlanChange.Status.CANCELLED)
        audit(actor, "payment.failed", "payment", payment.pk, f"{payment.reference} for {payment.subscription.restaurant.slug}: {reason}")
    return payment


def apply_due_plan_changes(now=None):
    """Move a subscription onto the cheaper plan once the billing period that was paid for it has begun. Until then the
    running period (and everything in it) is untouched. Returns how many were applied."""
    now = now or timezone.now()
    applied = 0
    with transaction.atomic():
        due = PlanChange.objects.select_for_update(of=("self",)).select_related("subscription", "to_plan").filter(
            kind=PlanChange.Kind.DOWNGRADE, status=PlanChange.Status.PENDING, effective_at__lte=now)
        for change in due:
            started = BillingPeriod.objects.filter(subscription=change.subscription, plan=change.to_plan, starts_at__gte=change.effective_at, starts_at__lte=now).first()
            if started is None:
                continue  # not renewed yet: the restaurant is still on its current plan
            sub = Subscription.objects.select_for_update().get(pk=change.subscription_id)
            sub.plan, sub.pending_plan = change.to_plan, None
            sub.save(update_fields=["plan", "pending_plan", "updated_at"])
            change.status, change.applied_at = PlanChange.Status.APPLIED, now
            change.save(update_fields=["status", "applied_at"])
            audit(None, "subscription.downgraded", "subscription", sub.pk, f"{sub.restaurant.slug} now on {change.to_plan.name}")
            applied += 1
    return applied


# ---------- API credentials ----------
def hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def create_credential(*, actor, customer, name, environment, rate_limit_per_minute=None, monthly_request_limit=None):
    """Returns (credential, secret). The secret exists only in this return value; only its hash is stored."""
    # Limits left blank follow the restaurant's CURRENT plan (apikeys resolves them on every request), so editing a plan in
    # Plans & Pricing changes every key that hasn't been given its own numbers.
    for _ in range(5):
        secret = f"sf_{environment}_{secrets.token_urlsafe(32)}"
        try:
            with transaction.atomic():
                credential = ApiCredential.objects.create(
                    restaurant=customer, name=name, environment=environment, prefix=secret[:12], secret_hash=hash_secret(secret),
                    rate_limit_per_minute=rate_limit_per_minute, monthly_request_limit=monthly_request_limit, created_by=actor,
                )
                audit(actor, "credential.created", "credential", credential.pk, f"{credential.prefix} for {customer.slug}")
            return credential, secret
        except IntegrityError:
            continue  # a prefix collision is astronomically rare; try a new secret
    raise Conflict("Couldn't generate a unique credential. Try again.", code="credential_generation_failed")


def revoke_credential(credential_id, actor):
    with transaction.atomic():
        credential = get_object_or_404(ApiCredential.objects.select_for_update(), pk=credential_id)
        if credential.status == ApiCredential.Status.REVOKED:
            raise Conflict("This credential is already revoked.", code="already_revoked")
        credential.status = ApiCredential.Status.REVOKED
        credential.revoked_at = timezone.now()
        credential.revoked_by = actor
        credential.save(update_fields=["status", "revoked_at", "revoked_by"])
        audit(actor, "credential.revoked", "credential", credential.pk, f"{credential.prefix}")
    from . import apikeys  # local import: apikeys imports this module

    apikeys.forget(credential.secret_hash)  # a revoked key stops working at once
    return credential


# ---------- metering ----------
def record_usage(restaurant_id, method, path, *, error=False, day=None):
    """Count one request in a single atomic upsert (PostgreSQL), so concurrent requests never lose a count.
    `error` means a server failure (HTTP 5xx); client errors such as 404 or validation failures are normal use."""
    table = connection.ops.quote_name(ApiUsageDaily._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f'INSERT INTO {table} (restaurant_id, "date", method, path, requests, errors) VALUES (%s, %s, %s, %s, 1, %s) '
            f'ON CONFLICT (restaurant_id, "date", method, path) DO UPDATE '
            f"SET requests = {table}.requests + 1, errors = {table}.errors + EXCLUDED.errors",
            [restaurant_id, day or timezone.localdate(), method[:8], path[:200], 1 if error else 0],
        )


def record_rate_limit_event(restaurant_id, endpoint, limit, credential_id=None):
    return RateLimitEvent.objects.create(restaurant_id=restaurant_id, endpoint=endpoint[:200], limit=limit, credential_id=credential_id)
