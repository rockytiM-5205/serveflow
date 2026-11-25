"""What the platform owner does to a restaurant account: create it together with its one admin, edit it, reset the admin's
password, give or change time and plan, delete an empty one. Every change is audited."""
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.common.exceptions import Conflict
from apps.restaurants.models import MembershipRole, Restaurant, RestaurantMembership
from apps.restaurants.services import check_password_strength

from . import locks, usage
from .models import ApiCredential, ApiUsageDaily, BillingPeriod, OrderPack, Plan, RateLimitEvent, Subscription
from .services import audit, start_trial

OWNER = MembershipRole.OWNER


def _temporary_password(user):
    """A random starting password that passes the project's own password rules. Shown to the platform owner once."""
    for _ in range(8):
        candidate = secrets.token_urlsafe(9)
        try:
            password_validation.validate_password(candidate, user)
            return candidate
        except DjangoValidationError:
            continue
    raise Conflict("Couldn't generate a password. Try again.", code="password_generation_failed")


def admin_of(restaurant):
    membership = (RestaurantMembership.objects.select_related("user")
                  .filter(restaurant=restaurant, role=OWNER, is_active=True).order_by("id").first())
    return membership.user if membership else None


def create_customer(*, actor, data, admin, plan=None, start_trial_now=True):
    """Create the restaurant AND its one admin together. Returns (restaurant, admin_user, temporary_password|None, subscription|None)."""
    User = get_user_model()
    email = admin["email"].strip().lower()
    with transaction.atomic():
        user = User.objects.filter(email=email).first()
        temporary = None
        if user is None:
            probe = User(email=email, first_name=admin.get("first_name", ""), last_name=admin.get("last_name", ""))
            password = admin.get("password") or ""
            if password:
                check_password_strength(password, probe, field="admin_password")
            else:
                password = temporary = _temporary_password(probe)
            user = User.objects.create_user(email, password, first_name=probe.first_name, last_name=probe.last_name)
        else:
            if user.is_superuser:
                raise Conflict("A platform owner can't also be a restaurant admin. Use a different email.", code="admin_is_platform_owner")
            if not user.is_active:
                raise Conflict("That account is switched off.", code="admin_inactive")
            if RestaurantMembership.objects.filter(user=user, role=OWNER, is_active=True).exists():
                raise Conflict("That person already runs a restaurant. Each admin has exactly one.", code="admin_has_restaurant")
        restaurant = Restaurant(**data)
        restaurant._skip_auto_trial = True  # we start the trial ourselves, on the plan you chose
        restaurant.save()
        RestaurantMembership.objects.create(restaurant=restaurant, user=user, role=OWNER)
        audit(actor, "customer.created", "restaurant", restaurant.pk, restaurant.slug)
        subscription = None
        if start_trial_now:
            subscription = start_trial(restaurant, plan, actor=actor)  # always on the free trial; `plan` is what they intend to buy
    return restaurant, user, temporary, subscription


def update_customer_admin(restaurant, actor, data):
    user = admin_of(restaurant)
    if user is None:
        raise Conflict("This restaurant has no active admin.", code="no_admin")
    User = get_user_model()
    with transaction.atomic():
        if "email" in data:
            email = data["email"].strip().lower()
            if User.objects.filter(email=email).exclude(pk=user.pk).exists():
                raise Conflict("Another account already uses that email.", code="email_taken")
            user.email = email
        for field in ("first_name", "last_name"):
            if field in data:
                setattr(user, field, data[field].strip())
        user.save()
        audit(actor, "customer.admin_updated", "restaurant", restaurant.pk, restaurant.slug)
    return user


def reset_admin_password(restaurant, actor):
    user = admin_of(restaurant)
    if user is None:
        raise Conflict("This restaurant has no active admin.", code="no_admin")
    password = _temporary_password(user)
    with transaction.atomic():
        user.set_password(password)  # also signs the admin out everywhere (sessions are tied to the password hash)
        user.save(update_fields=["password"])
        audit(actor, "customer.admin_password_reset", "restaurant", restaurant.pk, restaurant.slug)
    return password


def extend_access(restaurant_id, actor, days, reason=""):
    """Give a restaurant more time (a goodwill extension, or a manual fix). A trial or ended subscription becomes a trial again."""
    with transaction.atomic():
        restaurant = get_object_or_404(Restaurant, pk=restaurant_id)
        sub = Subscription.objects.select_for_update().filter(restaurant=restaurant).first()
        if sub is None:
            raise Conflict("This restaurant has no subscription yet. Choose a plan for it first.", code="no_subscription")
        now = timezone.now()
        old_end = sub.current_period_end
        base = max(now, old_end)
        end = base + timedelta(days=days)
        if sub.status in (Subscription.Status.TRIAL, Subscription.Status.EXPIRED, Subscription.Status.CANCELLED):
            sub.status, sub.trial_ends_at = Subscription.Status.TRIAL, end
            sub.current_period_start = now if base == now else sub.current_period_start
        else:
            sub.status = Subscription.Status.ACTIVE
        sub.current_period_end = end
        sub.save()
        if base == now:
            usage.open_period(sub, sub.plan, now, end)  # it had lapsed: a fresh period (and allowance) starts now
        else:
            BillingPeriod.objects.filter(subscription=sub, ends_at=old_end).update(ends_at=end)  # same period, longer; usage is kept
        audit(actor, "customer.access_extended", "restaurant", restaurant.pk, f"{restaurant.slug} +{days} days. {reason}".strip()[:255])
    locks.forget(restaurant.slug)
    return sub


def change_plan(restaurant_id, actor, plan):
    """Put a restaurant on a paid plan. A paying (ACTIVE or PAST_DUE) restaurant moves onto it at once. One still on the free
    trial, or locked, is marked as intending to buy it, and moves onto it when its payment is confirmed."""
    if plan.is_trial or plan.status != Plan.Status.ACTIVE:
        raise Conflict("That plan isn't available.", code="plan_archived")
    with transaction.atomic():
        restaurant = get_object_or_404(Restaurant, pk=restaurant_id)
        sub = Subscription.objects.select_for_update().filter(restaurant=restaurant).first()
        if sub is None:
            sub = start_trial(restaurant, plan, actor=actor)
        elif sub.status in (Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE):
            sub.plan, sub.next_plan = plan, None
            sub.save(update_fields=["plan", "next_plan", "updated_at"])
            audit(actor, "customer.plan_changed", "restaurant", restaurant.pk, f"{restaurant.slug} now on {plan.name}")
        else:
            sub.next_plan = plan
            sub.save(update_fields=["next_plan", "updated_at"])
            audit(actor, "customer.plan_changed", "restaurant", restaurant.pk, f"{restaurant.slug} will pay for {plan.name}")
    locks.forget(restaurant.slug)
    return sub


def delete_customer(restaurant_id, actor):
    """Only a restaurant with no orders, menu or history can go. Anything else must be suspended: its records are kept."""
    User = get_user_model()
    try:
        with transaction.atomic():
            restaurant = get_object_or_404(Restaurant.objects.select_for_update(), pk=restaurant_id)
            slug = restaurant.slug
            admin_ids = list(RestaurantMembership.objects.filter(restaurant=restaurant).values_list("user_id", flat=True))
            ApiUsageDaily.objects.filter(restaurant=restaurant).delete()
            RateLimitEvent.objects.filter(restaurant=restaurant).delete()
            ApiCredential.objects.filter(restaurant=restaurant).delete()
            BillingPeriod.objects.filter(subscription__restaurant=restaurant).delete()  # refused (protected) if it has usage records
            Subscription.objects.filter(restaurant=restaurant).delete()  # refused (protected) if it has payments
            restaurant.delete()  # refused (protected) if it has orders, menu items or audit history
            User.objects.filter(pk__in=admin_ids, is_superuser=False, restaurant_memberships__isnull=True).update(is_active=False)
            audit(actor, "customer.deleted", "restaurant", restaurant_id, slug)
    except ProtectedError:
        raise Conflict("This restaurant has orders, menu or history, so it can't be deleted. Suspend it instead; its records are kept.",
                       code="customer_has_history") from None
    locks.forget(slug)


def grant_orders(restaurant_id, actor, orders, reason):
    """A manual billing adjustment: extra completed-order capacity for the restaurant's running period, free of charge. It is an
    ordinary order pack (so it expires with the period and shows in the usage history), flagged as granted by the owner. The reason
    is mandatory and the actor is recorded in the audit log. Nothing already counted is touched."""
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Conflict("Say why you are adding these orders (at least a few words). It is recorded in the audit log.", code="reason_required")
    if not isinstance(orders, int) or isinstance(orders, bool) or not 1 <= orders <= 10000:
        raise Conflict("Add between 1 and 10,000 orders.", code="invalid_orders")
    with transaction.atomic():
        restaurant = get_object_or_404(Restaurant, pk=restaurant_id)
        sub = Subscription.objects.select_for_update().select_related("plan").filter(restaurant=restaurant).first()
        period = usage.current_period(sub) if sub else None
        now = timezone.now()
        if period is None or now >= period.ends_at:
            raise Conflict("This restaurant has no running billing period to add orders to.", code="no_active_billing_period")
        pack = OrderPack.objects.create(
            restaurant=restaurant, billing_period=period, orders=orders, price=0, currency=period.currency,
            reference=f"ADJ-{secrets.token_hex(5).upper()}", status=OrderPack.Status.ACTIVE, activated_at=now,
        )
        audit(actor, "order_pack.granted", "restaurant", restaurant.pk, f"{restaurant.slug}: +{orders} orders until {period.ends_at:%Y-%m-%d} ({pack.reference}). Reason: {reason[:160]}")
    return pack
