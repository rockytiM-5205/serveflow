"""Read-only aggregates for the overview and usage pages. Only real rows are counted; with no data the
numbers are zero or omitted (an error rate with no requests is left out, never shown as 0%)."""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, When
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.orders.models import Order
from apps.restaurants.models import Restaurant

from . import usage as billing_usage
from .models import (
    ApiUsageDaily, BillingPeriod, OrderPack, OrderUsage, Plan, PlanChange, PlatformAuditEvent, RateLimitEvent, Subscription,
    SubscriptionPayment,
)


def usage_totals(start, end):
    agg = ApiUsageDaily.objects.filter(date__gte=start, date__lte=end).aggregate(n_requests=Sum("requests"), n_errors=Sum("errors"))
    requests, errors = agg["n_requests"] or 0, agg["n_errors"] or 0
    totals = {"requests": requests, "success": requests - errors, "failed": errors}
    if requests:
        totals["error_rate"] = round(errors / requests, 6)
    return totals


def usage_series(start, end):
    rows = (ApiUsageDaily.objects.filter(date__gte=start, date__lte=end).values("date")
            .annotate(n_requests=Sum("requests"), n_errors=Sum("errors")).order_by("date"))
    return [{"date": r["date"].isoformat(), "total": r["n_requests"], "errors": r["n_errors"]} for r in rows]


def usage_report(start, end):
    base = ApiUsageDaily.objects.filter(date__gte=start, date__lte=end)
    by_customer = [
        {"name": r["name"], "requests": r["n_requests"], "errors": r["n_errors"]}
        for r in base.values(name=F("restaurant__name")).annotate(n_requests=Sum("requests"), n_errors=Sum("errors")).order_by("-n_requests")[:20]]
    by_endpoint = [
        {"method": r["method"], "path": r["path"], "requests": r["n_requests"], "errors": r["n_errors"]}
        for r in base.values("method", "path").annotate(n_requests=Sum("requests"), n_errors=Sum("errors")).order_by("-n_requests")[:20]]
    events = (RateLimitEvent.objects.filter(occurred_at__date__gte=start, occurred_at__date__lte=end)
              .select_related("restaurant").order_by("-occurred_at")[:50])
    return {
        "totals": usage_totals(start, end), "series": usage_series(start, end), "by_customer": by_customer, "by_endpoint": by_endpoint,
        "rate_limit_events": [{"occurred_at": e.occurred_at, "customer_name": e.restaurant.name, "endpoint": e.endpoint, "limit": e.limit} for e in events],
    }


def revenue_series(start, end, currency="NGN", kinds=(SubscriptionPayment.Kind.SUBSCRIPTION, SubscriptionPayment.Kind.UPGRADE)):
    """Money by day. Subscription revenue (renewals and upgrades) and order-pack revenue are reported separately."""
    rows = (SubscriptionPayment.objects.filter(status=SubscriptionPayment.Status.CONFIRMED, kind__in=kinds, currency=currency, confirmed_at__date__gte=start, confirmed_at__date__lte=end)
            .annotate(day=TruncDate("confirmed_at")).values("day").annotate(total_amount=Sum("amount")).order_by("day"))
    return [{"date": r["day"].isoformat(), "amount": str(r["total_amount"])} for r in rows]


def monthly_recurring_revenue(currency="NGN"):
    monthly = ExpressionWrapper(
        Case(When(plan__interval=Plan.Interval.YEARLY, then=F("plan__price") / 12), default=F("plan__price"), output_field=DecimalField(max_digits=14, decimal_places=4)),
        output_field=DecimalField(max_digits=14, decimal_places=4))
    total = Subscription.objects.filter(status=Subscription.Status.ACTIVE, plan__currency=currency).aggregate(t=Sum(monthly))["t"] or Decimal("0")
    return {"amount": str(total.quantize(Decimal("0.01"))), "currency": currency}


def completed_orders_series(start, end):
    """Completed orders per day across the platform (the billable metric), straight from the order records."""
    rows = (Order.objects.filter(completed_at__date__gte=start, completed_at__date__lte=end)
            .annotate(day=TruncDate("completed_at")).values("day").annotate(n=Count("id")).order_by("day"))
    return [{"date": r["day"].isoformat(), "total": r["n"]} for r in rows]


def money_in_range(kinds, start, end, currency="NGN"):
    total = (SubscriptionPayment.objects.filter(status=SubscriptionPayment.Status.CONFIRMED, kind__in=kinds, currency=currency,
                                                confirmed_at__date__gte=start, confirmed_at__date__lte=end)
             .aggregate(t=Sum("amount"))["t"] or Decimal("0"))
    return {"amount": str(total.quantize(Decimal("0.01"))), "currency": currency}


def overview_report(days):
    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    prev_end, prev_start = start - timedelta(days=1), start - timedelta(days=days)
    totals = usage_totals(start, today)
    previous_usage = usage_totals(prev_start, prev_end)

    statuses = {value: 0 for value in Subscription.Status.values}
    for row in Subscription.objects.values("status").annotate(n=Count("id")):
        statuses[row["status"]] = row["n"]

    # `previous` carries only what can really be reconstructed: restaurants registered before the range, and
    # usage in the equal window before it. Subscription counts have no history, so they are left out.
    previous = {"customers": Restaurant.objects.filter(created_at__date__lt=start).count(),
                "completed_orders": Order.objects.filter(completed_at__date__gte=prev_start, completed_at__date__lte=prev_end).count()}
    if previous_usage["requests"]:
        previous["api_requests"] = previous_usage["requests"]
        previous["error_rate"] = previous_usage["error_rate"]

    events = [
        {"type": e.action, "occurred_at": e.created_at, "summary": e.summary}
        for e in PlatformAuditEvent.objects.order_by("-created_at", "-id")[:10]
    ] + [
        {"type": "customer.registered", "occurred_at": r.created_at, "summary": r.name}
        for r in Restaurant.objects.order_by("-created_at", "-id")[:5]
    ]
    events.sort(key=lambda e: e["occurred_at"], reverse=True)

    now = timezone.now()
    ending = Subscription.objects.filter(status=Subscription.Status.TRIAL, current_period_end__gt=now, current_period_end__lte=now + timedelta(hours=24))
    awaiting = SubscriptionPayment.objects.filter(status=SubscriptionPayment.Status.AWAITING_CONFIRMATION)
    attention = (
        [{"type": "payment_awaiting", "customer_id": p.subscription.restaurant_id, "name": p.subscription.restaurant.name,
          "detail": f"{p.reference} is waiting for you to confirm", "at": p.created_at}
         for p in awaiting.select_related("subscription__restaurant").order_by("created_at")[:5]]
        + [{"type": "trial_ending", "customer_id": s.restaurant_id, "name": s.restaurant.name, "detail": "Trial ends within 24 hours", "at": s.current_period_end}
           for s in ending.select_related("restaurant").order_by("current_period_end")[:5]]
        + [{"type": "expired", "customer_id": s.restaurant_id, "name": s.restaurant.name, "detail": "Subscription ended, restaurant is locked", "at": s.current_period_end}
           for s in Subscription.objects.filter(status=Subscription.Status.EXPIRED).select_related("restaurant").order_by("-current_period_end")[:5]]
    )
    recent = Restaurant.objects.select_related("subscription__plan").order_by("-created_at", "-id")[:6]
    return {
        "range": {"from": start.isoformat(), "to": today.isoformat()},
        "totals": {
            "customers": Restaurant.objects.count(),
            "active_subscriptions": statuses[Subscription.Status.ACTIVE],
            "mrr": monthly_recurring_revenue(),
            "overdue_subscriptions": statuses[Subscription.Status.PAST_DUE],
            "trials_running": statuses[Subscription.Status.TRIAL],
            "trials_ending_soon": ending.count(),
            "expired_subscriptions": statuses[Subscription.Status.EXPIRED],
            "payments_awaiting": awaiting.count(),
            "api_requests": totals["requests"],
            "completed_orders": Order.objects.filter(completed_at__date__gte=start, completed_at__date__lte=today).count(),
            "subscription_revenue": money_in_range((SubscriptionPayment.Kind.SUBSCRIPTION, SubscriptionPayment.Kind.UPGRADE), start, today),
            "order_pack_revenue": money_in_range((SubscriptionPayment.Kind.ORDER_PACK,), start, today),
            "failed_payments": SubscriptionPayment.objects.filter(status=SubscriptionPayment.Status.FAILED, created_at__date__gte=start).count(),
            **({"error_rate": totals["error_rate"]} if "error_rate" in totals else {}),
        },
        "previous": previous,
        "series": {"requests": usage_series(start, today), "revenue": revenue_series(start, today),
                   "order_pack_revenue": revenue_series(start, today, kinds=(SubscriptionPayment.Kind.ORDER_PACK,)),
                   "completed_orders": completed_orders_series(start, today)},
        "subscription_status": statuses,
        "recent_activity": events[:10],
        "attention": attention[:8],
        "recent_customers": [
            {"id": r.pk, "name": r.name, "account_id": r.slug, "registered_at": r.created_at,
             "subscription_status": getattr(getattr(r, "subscription", None), "status", None),
             "plan_name": getattr(getattr(getattr(r, "subscription", None), "plan", None), "name", None)}
            for r in recent
        ],
    }


def customer_usage(restaurant_id, days=30):
    since = timezone.localdate() - timedelta(days=days - 1)
    agg = ApiUsageDaily.objects.filter(restaurant_id=restaurant_id, date__gte=since).aggregate(n_requests=Sum("requests"), n_errors=Sum("errors"))
    requests, errors = agg["n_requests"] or 0, agg["n_errors"] or 0
    data = {"requests_30d": requests}
    if requests:
        data["error_rate"] = round(errors / requests, 6)
    return data


def customer_billing(sub):
    """One restaurant's billing picture for the owner: this period's usage, recent periods, packs and a waiting plan change."""
    if sub is None:
        return None
    periods = []
    for period in BillingPeriod.objects.filter(subscription=sub).order_by("-starts_at")[:6]:
        rows = OrderUsage.objects.filter(billing_period=period)
        periods.append({
            "starts_at": period.starts_at, "ends_at": period.ends_at, "plan_name": period.plan_name,
            "included_orders": period.included_orders, "completed_orders": rows.count(),
            "from_packs": rows.filter(charged_to=OrderUsage.ChargedTo.PACK).count(),
            "over_allowance": rows.filter(charged_to=OrderUsage.ChargedTo.OVERAGE).count(),
        })
    packs = [{"reference": p.reference, "orders": p.orders, "price": p.price, "currency": p.currency, "status": p.status,
              "granted_by_owner": p.reference.startswith("ADJ-"), "activated_at": p.activated_at, "created_at": p.created_at}
             for p in OrderPack.objects.filter(restaurant_id=sub.restaurant_id).order_by("-created_at", "-id")[:8]]
    change = PlanChange.objects.filter(subscription=sub, status=PlanChange.Status.PENDING).select_related("to_plan").first()
    return {
        "usage": billing_usage.summary(sub), "periods": periods, "order_packs": packs,
        "pending_plan_change": {"kind": change.kind, "to_plan": change.to_plan.name, "effective_at": change.effective_at,
                                "amount_due": change.amount_due} if change else None,
    }

