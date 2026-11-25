"""Orders completing at the same instant (real threads, real PostgreSQL connections) are counted once each, in order."""
import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connections
from django.utils import timezone

from apps.orders.models import ActorType, Order, OrderStatus
from apps.orders.workflow import change_status
from apps.platform_admin import usage
from apps.platform_admin.models import OrderUsage, Plan, Subscription

pytestmark = pytest.mark.django_db(transaction=True)


def run_in_threads(jobs):
    results = [None] * len(jobs)

    def worker(index, job):
        try:
            results[index] = job()
        except Exception as exc:  # reported by the assertions below
            results[index] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i, job)) for i, job in enumerate(jobs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


def test_simultaneous_completions_are_each_counted_once_and_split_between_plan_and_overage(shop, order_in):
    plan = Plan.objects.create(
        name="Tiny", interval="MONTHLY", price=Decimal("1.00"), included_orders=4, included_requests=1000, rate_limit_per_minute=60,
    )
    now = timezone.now()
    sub = Subscription.objects.create(
        restaurant=shop.restaurant, plan=plan, status="ACTIVE", started_at=now, current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=29), billing_anchor=now - timedelta(days=1),
    )
    usage.open_period(sub, plan, sub.current_period_start, sub.current_period_end)
    orders = [order_in("SERVING", phone=f"+44207946{n:04d}") for n in range(1, 7)]

    def job(order):
        return lambda: change_status(order=order, to_status=OrderStatus.COMPLETED, actor_type=ActorType.SYSTEM).status

    results = run_in_threads([job(order) for order in orders])

    assert results == ["COMPLETED"] * 6
    assert OrderUsage.objects.count() == 6
    assert OrderUsage.objects.values("order").distinct().count() == 6
    assert OrderUsage.objects.filter(charged_to="PLAN").count() == 4  # never more than the allowance
    assert OrderUsage.objects.filter(charged_to="OVERAGE").count() == 2
    assert Order.objects.filter(status="COMPLETED").count() == 6


def test_the_same_order_completed_twice_at_once_is_counted_once(shop, order_in):
    plan = Plan.objects.create(
        name="Tiny2", interval="MONTHLY", price=Decimal("1.00"), included_orders=10, included_requests=1000, rate_limit_per_minute=60,
    )
    now = timezone.now()
    sub = Subscription.objects.create(
        restaurant=shop.restaurant, plan=plan, status="ACTIVE", started_at=now, current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=29), billing_anchor=now - timedelta(days=1),
    )
    usage.open_period(sub, plan, sub.current_period_start, sub.current_period_end)
    order = order_in("SERVING")

    def job():
        return change_status(order=order, to_status=OrderStatus.COMPLETED, actor_type=ActorType.SYSTEM).status

    results = run_in_threads([job, job])

    assert sorted(type(r).__name__ for r in results) == ["Conflict", "str"]  # one wins, the other is refused
    assert OrderUsage.objects.filter(order=order).count() == 1
