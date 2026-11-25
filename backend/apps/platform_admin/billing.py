"""What a restaurant owner sees and does about their ServeFlow subscription: pick a plan, get the bank details and a
payment reference, report the transfer. The owner of ServeFlow then confirms it (services.confirm_payment); nothing here
can mark anything paid."""
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import Conflict

from . import locks
from .models import OrderPack, PaymentDetails, PlanChange, Plan, Subscription, SubscriptionPayment
from .notifications import notify
from .serializers import PlanSerializer
from . import usage
from .services import audit, start_trial


def payment_details():
    return PaymentDetails.objects.first()


def public_payment_info():
    """Safe for anyone: the method and the owner's note, never account numbers."""
    details = payment_details()
    return {"method": "BANK_TRANSFER", "ready": bool(details and details.ready), "instructions": details.instructions if details else ""}


def private_payment_info(details):
    if not (details and details.ready):
        return None
    return {"bank_name": details.bank_name, "account_name": details.account_name, "account_number": details.account_number, "instructions": details.instructions}


def active_plans():
    return PlanSerializer(Plan.objects.filter(status=Plan.Status.ACTIVE, is_trial=False).order_by("price", "id"), many=True).data


def _payment_row(p):
    return {"id": p.pk, "reference": p.reference, "kind": p.kind, "amount": p.amount, "currency": p.currency, "status": p.status, "provider": p.provider, "created_at": p.created_at}


def paid_plan_of(sub):
    """The paid plan a renewal payment would buy: the one they chose, a downgrade waiting for the next period, or the paid plan
    they're already on."""
    if sub.next_plan_id:
        return sub.next_plan
    if sub.pending_plan_id:
        return sub.pending_plan
    return None if sub.plan.is_trial else sub.plan


def overview(restaurant):
    sub = Subscription.objects.select_related("plan", "next_plan", "pending_plan").filter(restaurant=restaurant).first()
    payments = list(SubscriptionPayment.objects.filter(subscription=sub).order_by("-created_at", "-id")[:20]) if sub else []
    awaiting = [p for p in payments if p.status == SubscriptionPayment.Status.AWAITING_CONFIRMATION]
    open_payment = next((p for p in awaiting if p.kind == SubscriptionPayment.Kind.SUBSCRIPTION), None)
    to_pay = paid_plan_of(sub) if sub else None
    packs = list(OrderPack.objects.filter(restaurant=restaurant).select_related("billing_period").order_by("-created_at", "-id")[:10])
    change = PlanChange.objects.filter(subscription=sub, status=PlanChange.Status.PENDING).select_related("to_plan").first() if sub else None
    offer = _pack_offer(sub)
    return {
        "subscription": {
            "status": sub.status, "plan": PlanSerializer(sub.plan).data, "next_plan": PlanSerializer(sub.next_plan).data if sub.next_plan_id else None,
            "plan_to_pay": PlanSerializer(to_pay).data if to_pay else None, "current_period_start": sub.current_period_start,
            "current_period_end": sub.current_period_end, "trial_ends_at": sub.trial_ends_at,
        } if sub else None,
        "usage": usage.summary(sub) if sub else None,
        "pack_offer": offer,
        "order_packs": [_pack_row(p) for p in packs],
        "pending_plan_change": {
            "kind": change.kind, "to_plan": PlanSerializer(change.to_plan).data, "effective_at": change.effective_at,
            "amount_due": change.amount_due,
        } if change else None,
        "open_extra_payments": [_payment_row(p) for p in awaiting if p.kind != SubscriptionPayment.Kind.SUBSCRIPTION],
        "plans": active_plans(),
        "payments": [_payment_row(p) for p in payments],
        "open_payment": _payment_row(open_payment) if open_payment else None,
        "payment_details": private_payment_info(payment_details()),
        "payment_info": public_payment_info(),
    }


def choose_plan(restaurant, plan, actor):
    """Pick the paid plan they'll buy. It doesn't change what they're on (the free trial) until a payment is confirmed."""
    if plan.is_trial or plan.status != Plan.Status.ACTIVE:
        raise Conflict("That plan is no longer available.", code="plan_archived")
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().filter(restaurant=restaurant).first()
        if sub is None:
            sub = start_trial(restaurant, plan, actor=actor)
        elif sub.status in (Subscription.Status.TRIAL, Subscription.Status.EXPIRED, Subscription.Status.CANCELLED) or sub.plan.is_trial:
            sub.next_plan = plan
            if sub.status == Subscription.Status.CANCELLED:
                sub.status = Subscription.Status.EXPIRED  # choosing a plan again; paying reactivates it
            sub.save(update_fields=["next_plan", "status", "updated_at"])
            audit(actor, "subscription.plan_chosen", "subscription", sub.pk, f"{restaurant.slug} chose {plan.name}")
        else:
            return _change_paying_plan(restaurant, sub, plan, actor)
    locks.forget(restaurant.slug)
    return sub


def open_payment(restaurant, actor):
    """Returns (payment, created). One open payment per subscription; asking again returns the same reference."""
    details = payment_details()
    if not (details and details.ready):
        raise Conflict("ServeFlow hasn't published payment details yet. Please try again later.", code="payment_details_missing")
    sub = Subscription.objects.select_related("plan", "next_plan").filter(restaurant=restaurant).first()
    if sub is None:
        raise Conflict("Choose a plan first.", code="no_subscription")
    if sub.status == Subscription.Status.CANCELLED:
        raise Conflict("Choose a plan again before paying.", code="subscription_cancelled")
    plan = paid_plan_of(sub)
    if plan is None:
        raise Conflict("Choose the plan you want to pay for first.", code="no_plan_chosen")
    with transaction.atomic():
        existing = SubscriptionPayment.objects.select_for_update().filter(
            subscription=sub, kind=SubscriptionPayment.Kind.SUBSCRIPTION, status=SubscriptionPayment.Status.AWAITING_CONFIRMATION).first()
        if existing:
            return existing, False
        for _ in range(5):
            try:
                with transaction.atomic():
                    payment = SubscriptionPayment.objects.create(
                        subscription=sub, reference=f"SF-{secrets.token_hex(4).upper()}", amount=plan.price,
                        currency=plan.currency, transacted_at=timezone.now())
                break
            except IntegrityError:
                continue
        else:
            raise Conflict("Couldn't create a payment reference. Try again.", code="reference_failed")
        audit(actor, "payment.reported", "payment", payment.pk, f"{payment.reference} for {restaurant.slug}")
        notify("payment_reported", f"{restaurant.name} reported a transfer", f"{payment.reference} · {payment.amount} {payment.currency}. Confirm it when it arrives.",
               "#/payments", restaurant, f"payment:{payment.pk}")
    return payment, True


# ---------------------------------------------------------------- order packs, upgrades, downgrades
def _pack_offer(sub):
    """The pack this restaurant can buy right now (from the plan of its running period), or None."""
    if sub is None or sub.status != Subscription.Status.ACTIVE:
        return None
    period = usage.current_period(sub)
    if period is None or timezone.now() >= period.ends_at or not (period.plan.pack_orders and period.plan.pack_price):
        return None
    return {"orders": period.plan.pack_orders, "price": period.plan.pack_price, "currency": period.plan.currency, "expires_at": period.ends_at}


def _pack_row(pack):
    used = pack.usage.count()
    return {
        "reference": pack.reference, "orders": pack.orders, "price": pack.price, "currency": pack.currency, "status": pack.status,
        "used": used, "remaining": max(pack.orders - used, 0) if pack.status == OrderPack.Status.ACTIVE else 0,
        "activated_at": pack.activated_at, "expires_at": pack.billing_period.ends_at, "created_at": pack.created_at,
    }


def _new_payment(sub, prefix, amount, currency, **extra):
    for _ in range(5):
        try:
            with transaction.atomic():
                return SubscriptionPayment.objects.create(
                    subscription=sub, reference=f"SF-{prefix}-{secrets.token_hex(4).upper()}", amount=amount, currency=currency,
                    transacted_at=timezone.now(), **extra)
        except IntegrityError:
            continue
    raise Conflict("Couldn't create a payment reference. Try again.", code="reference_failed")


def _require_bank_details():
    details = payment_details()
    if not (details and details.ready):
        raise Conflict("ServeFlow hasn't published payment details yet. Please try again later.", code="payment_details_missing")


def purchase_order_pack(restaurant, actor):
    """Start buying one order pack for the running billing period. Returns (payment, pack, created). The pack adds nothing
    until its payment is confirmed server-side; it can only be used until the period ends and never renews."""
    _require_bank_details()
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().select_related("plan").filter(restaurant=restaurant).first()
        if sub is None:
            raise Conflict("Choose a plan first.", code="no_subscription")
        offer = _pack_offer(sub)
        if offer is None:
            raise Conflict("Order packs aren't available on your current plan or billing period.", code="order_packs_unavailable")
        existing = SubscriptionPayment.objects.select_for_update().select_related("order_pack").filter(
            subscription=sub, kind=SubscriptionPayment.Kind.ORDER_PACK, status=SubscriptionPayment.Status.AWAITING_CONFIRMATION).first()
        if existing:
            return existing, existing.order_pack, False
        period = usage.current_period(sub)
        payment = _new_payment(sub, "PK", offer["price"], offer["currency"], kind=SubscriptionPayment.Kind.ORDER_PACK, order_pack=_new_pack(restaurant, period, offer))
        pack = payment.order_pack
        # The pack shares its payment's reference, so the purchase and the payment can never be confused.
        OrderPack.objects.filter(pk=pack.pk).update(reference=payment.reference)
        pack.reference = payment.reference
        audit(actor, "order_pack.requested", "order_pack", pack.pk, f"{payment.reference} for {restaurant.slug}: {offer['orders']} orders")
        notify("payment_reported", f"{restaurant.name} wants an order pack", f"{payment.reference} · {payment.amount} {payment.currency}. Confirm it when it arrives.",
               "#/payments", restaurant, f"payment:{payment.pk}")
    return payment, pack, True


def _new_pack(restaurant, period, offer):
    return OrderPack.objects.create(
        restaurant=restaurant, billing_period=period, orders=offer["orders"], price=offer["price"], currency=offer["currency"],
        reference=f"PENDING-{secrets.token_hex(8).upper()}",
    )


def _change_paying_plan(restaurant, sub, plan, actor):
    """A restaurant can ask to switch plan at any time, in either direction.

    * A dearer plan on the same interval and currency is an UPGRADE: pay the price difference (no proration by time, nothing
      invented) and it applies at once to the running period.
    * Anything else (a cheaper plan, a monthly/yearly change, another currency) is SCHEDULED for the next billing anniversary,
      so what was already paid for isn't taken away. The next renewal is then priced at the new plan.
    * A restaurant that is overdue just has its next payment priced at the plan it picks.
    * Asking again replaces a change that was waiting; choosing the current plan cancels it.
    """
    current = sub.plan
    waiting = PlanChange.objects.filter(subscription=sub, status=PlanChange.Status.PENDING).first()
    if plan.pk == current.pk:
        if waiting is None:
            raise Conflict("You're already on that plan.", code="same_plan")
        cancel_pending_change(restaurant, actor)
        return Subscription.objects.get(pk=sub.pk)
    if waiting is not None:
        cancel_pending_change(restaurant, actor)
        sub = Subscription.objects.select_for_update().select_related("plan").get(pk=sub.pk)
    if sub.status != Subscription.Status.ACTIVE:  # overdue: nothing is running to change, so the next payment follows the new plan
        sub.next_plan = plan
        sub.save(update_fields=["next_plan", "updated_at"])
        audit(actor, "subscription.plan_chosen", "subscription", sub.pk, f"{restaurant.slug}: {plan.name} (overdue)")
        return sub
    now = timezone.now()
    period = usage.current_period(sub, now)
    same_terms = plan.interval == current.interval and plan.currency == current.currency
    if plan.price > current.price and same_terms:
        _require_bank_details()
        if period is None or now >= period.ends_at:
            raise Conflict("There is no running billing period to upgrade.", code="no_active_billing_period")
        change = PlanChange.objects.create(
            subscription=sub, restaurant=restaurant, from_plan=current, to_plan=plan, kind=PlanChange.Kind.UPGRADE,
            billing_period=period, amount_due=plan.price - current.price, requested_by=actor,
        )
        payment = _new_payment(sub, "UP", change.amount_due, plan.currency, kind=SubscriptionPayment.Kind.UPGRADE, plan_change=change)
        audit(actor, "subscription.upgrade_requested", "subscription", sub.pk, f"{restaurant.slug}: {current.name} to {plan.name}, {payment.reference}")
        notify("payment_reported", f"{restaurant.name} wants to upgrade", f"{payment.reference} · {payment.amount} {payment.currency}. Confirm it when it arrives.",
               "#/payments", restaurant, f"payment:{payment.pk}")
    else:
        PlanChange.objects.create(
            subscription=sub, restaurant=restaurant, from_plan=current, to_plan=plan, kind=PlanChange.Kind.DOWNGRADE,
            effective_at=sub.current_period_end, requested_by=actor,
        )
        sub.pending_plan = plan
        sub.save(update_fields=["pending_plan", "updated_at"])
        audit(actor, "subscription.change_scheduled", "subscription", sub.pk, f"{restaurant.slug}: {current.name} to {plan.name} on {sub.current_period_end:%Y-%m-%d}")
    return sub


def cancel_pending_change(restaurant, actor):
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().filter(restaurant=restaurant).first()
        change = PlanChange.objects.select_for_update().filter(subscription=sub, status=PlanChange.Status.PENDING).first() if sub else None
        if change is None:
            raise Conflict("There is no plan change to cancel.", code="no_pending_change")
        change.status = PlanChange.Status.CANCELLED
        change.save(update_fields=["status"])
        SubscriptionPayment.objects.filter(plan_change=change, status=SubscriptionPayment.Status.AWAITING_CONFIRMATION).update(
            status=SubscriptionPayment.Status.FAILED, failure_reason="Cancelled by the restaurant")
        if sub.pending_plan_id:
            sub.pending_plan = None
            sub.save(update_fields=["pending_plan", "updated_at"])
        audit(actor, "subscription.plan_change_cancelled", "subscription", sub.pk, restaurant.slug)
    return sub
