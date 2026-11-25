"""The late pickup policy, in one place.

Each restaurant decides whether to charge customers who collect late and how much. The rules are shown to the customer before they
order, they must accept them, and they are copied onto the order, so a later change never alters an order already placed.

The clock never starts until the restaurant says the order is ready (READY_FOR_PICKUP), so the restaurant can't charge for its own
delay. It starts at the later of "ready" and the pickup time the customer chose, then there is a free grace period, then a fee for
every full or part interval after that, never more than the restaurant's maximum. The fee is worked out once, when the order is
completed (collected). Staff then mark it collected or waive it; both are recorded.
"""
import math
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import Fulfilment

TWO_PLACES = Decimal("0.01")


def snapshot(restaurant):
    """The policy as it stands, in plain values that can be stored on the order."""
    return {
        "grace_minutes": restaurant.late_grace_minutes, "fee_amount": str(restaurant.late_fee_amount),
        "interval_minutes": restaurant.late_fee_interval_minutes, "max_fee": str(restaurant.late_fee_max),
    }


def free_until(order):
    """When the free period ends, or None while the order isn't ready (no clock yet) or has no policy."""
    policy = order.late_policy
    if not policy or order.ready_at is None or order.fulfilment_type != Fulfilment.PICKUP:
        return None
    start = max(order.ready_at, order.pickup_at) if order.pickup_at else order.ready_at
    return start + timedelta(minutes=int(policy["grace_minutes"]))


def late_minutes(order, collected_at):
    until = free_until(order)
    if until is None or collected_at <= until:
        return 0
    return math.ceil((collected_at - until).total_seconds() / 60)


def compute_late_fee(order, collected_at=None):
    """(fee, minutes_late). Zero when there is no policy, the order was never marked ready, or it was collected in time."""
    minutes = late_minutes(order, collected_at or timezone.now())
    if minutes == 0:
        return Decimal("0.00"), 0
    policy = order.late_policy
    intervals = math.ceil(minutes / int(policy["interval_minutes"]))
    fee = min(Decimal(policy["fee_amount"]) * intervals, Decimal(policy["max_fee"]))
    return fee.quantize(TWO_PLACES), minutes
