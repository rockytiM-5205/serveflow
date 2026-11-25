"""The order status machine. Every status change goes through change_status()."""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import record
from apps.platform_admin import usage
from apps.common.exceptions import Conflict

from . import lateness
from .models import ActorType, LateFeeStatus, Order, OrderStatus, OrderStatusEvent, PaymentStatus

S = OrderStatus
# PENDING -> CONFIRMED -> SERVING (preparing) -> READY_FOR_PICKUP -> COMPLETED. READY_FOR_PICKUP is optional (dine-in
# kitchens may go straight from preparing to completed); a pickup timer only exists once an order was marked ready.
LEGAL = {
    S.PENDING: {S.CONFIRMED, S.REJECTED, S.CANCELLED},
    S.CONFIRMED: {S.SERVING, S.CANCELLED},
    S.SERVING: {S.READY_FOR_PICKUP, S.COMPLETED, S.CANCELLED},
    S.READY_FOR_PICKUP: {S.COMPLETED, S.CANCELLED},
}
IN_PROGRESS = {S.SERVING, S.READY_FOR_PICKUP}  # cancelling these needs a manager who acknowledges it
REASON_REQUIRED = {S.REJECTED, S.CANCELLED}
MANAGER_ACTORS = {ActorType.MANAGER, ActorType.OWNER}


def actor_type_for(role):
    return ActorType(role)  # membership roles share names with the staff actor types


CHAIN = [S.PENDING, S.CONFIRMED, S.SERVING, S.READY_FOR_PICKUP, S.COMPLETED]


def steps_to(current, target):
    """The statuses an order passes through to get from `current` to `target`, or None if that isn't a forward move along the normal path.
    READY_FOR_PICKUP is optional, so it is skipped when the target is COMPLETED."""
    if current not in CHAIN or target not in CHAIN:
        return None
    i, j = CHAIN.index(current), CHAIN.index(target)
    path = CHAIN[i + 1 : j + 1] if j > i else []
    if target == S.COMPLETED and S.READY_FOR_PICKUP in path:
        path.remove(S.READY_FOR_PICKUP)
    return path


def advance_to(*, order, to_status, actor_type, actor_user=None):
    """Move an order forward to `to_status`, passing through the steps in between (accepting a pending order on the way to preparing).
    Every step goes through change_status(), so the payment rule and the history are exactly the same as pressing each button.
    All steps or none: if one is refused, the order is left where it was."""
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        steps = steps_to(locked.status, to_status)
        if not steps:
            raise Conflict(
                f"This order is already {OrderStatus(locked.status).label.lower()}.", code="already_there" if steps == [] else "invalid_transition",
                details={"status": locked.status},
            )
        for step in steps:
            locked = change_status(order=locked, to_status=step, actor_type=actor_type, actor_user=actor_user)
    return locked


def change_status(*, order, to_status, actor_type, actor_user=None, reason="", expected_status=None, acknowledge_serving=False):
    """Move an order to `to_status`, or raise.

    Customers may only cancel a PENDING order. Staff cancel before SERVING; cancelling an order
    that is already being served needs a manager or owner who explicitly acknowledges it.
    The order row is locked, so two people acting at once cannot both succeed.
    """
    reason = (reason or "").strip()
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        current = locked.status

        if expected_status and current != expected_status:
            raise Conflict(
                "This order has changed since you opened it.", code="stale_status", details={"current_status": current}
            )
        if to_status not in LEGAL.get(current, set()):
            raise Conflict(
                f"An order that is {OrderStatus(current).label.lower()} can't become "
                f"{OrderStatus(to_status).label.lower()}.",
                code="invalid_transition",
                details={"from": current, "to": to_status},
            )
        if actor_type == ActorType.CUSTOMER and not (current == S.PENDING and to_status == S.CANCELLED):
            raise Conflict("Only a pending order can be cancelled.", code="invalid_transition", details={"from": current, "to": to_status})
        if actor_type == ActorType.CUSTOMER and locked.payment_status in (PaymentStatus.CLAIMED, PaymentStatus.PAID):
            raise Conflict(
                "You've already paid for this order, so please contact the restaurant to cancel it and arrange a refund.",
                code="paid_order", details={"payment_status": locked.payment_status},
            )
        if to_status == S.SERVING and locked.payment_status != PaymentStatus.PAID:
            # Customers pay first. Nothing is cooked until the restaurant has confirmed the money arrived.
            raise Conflict(
                "Confirm the customer's payment before preparing this order.", code="payment_required",
                details={"payment_status": locked.payment_status},
            )
        if current in IN_PROGRESS and to_status == S.CANCELLED:
            if actor_type not in MANAGER_ACTORS:
                raise PermissionDenied(
                    "Only managers and owners can cancel an order that is already being served.", code="manager_required"
                )
            if not acknowledge_serving:
                raise ValidationError({"acknowledge_serving": ["Confirm that you want to cancel an order that is being served."]})
        if to_status in REASON_REQUIRED and actor_type != ActorType.CUSTOMER and not reason:
            raise ValidationError({"reason": ["Give a reason."]})

        now = timezone.now()
        locked.status = to_status
        fields = ["status", "updated_at"]
        if to_status == S.READY_FOR_PICKUP:
            locked.ready_at = now
            fields.append("ready_at")
        if to_status == S.COMPLETED:
            locked.completed_at = now
            fields.append("completed_at")
            fee, minutes = lateness.compute_late_fee(locked, now)  # collected late? worked out once, from the rules the customer accepted
            if fee > 0:
                locked.late_fee, locked.late_fee_status = fee, LateFeeStatus.DUE
                fields += ["late_fee", "late_fee_status"]
        locked.save(update_fields=fields)
        OrderStatusEvent.objects.create(
            order=locked, restaurant=locked.restaurant, from_status=current, to_status=to_status,
            actor_type=actor_type, actor_user=actor_user, reason=reason,
        )
        if to_status == S.COMPLETED:
            # The one billable event. Same transaction and same order lock: the status change and its usage row
            # commit together or not at all.
            usage.record_completion(locked, now=now)
        if to_status == S.COMPLETED and locked.late_fee_status == LateFeeStatus.DUE:
            record(
                restaurant=locked.restaurant, actor=actor_user, action="order.late_fee_due", entity_type="order",
                entity_id=locked.pk, metadata={"code": locked.code, "fee": str(locked.late_fee), "minutes_late": minutes},
            )
        if to_status in (S.CANCELLED, S.REJECTED) and locked.payment_status == PaymentStatus.PAID:
            record(
                restaurant=locked.restaurant, actor=actor_user, action="order.refund_due", entity_type="order",
                entity_id=locked.pk, metadata={"code": locked.code, "amount": str(locked.total), "reason": reason},
            )
        if current in IN_PROGRESS and to_status == S.CANCELLED:
            record(
                restaurant=locked.restaurant, actor=actor_user, action="order.cancelled_while_serving",
                entity_type="order", entity_id=locked.pk, metadata={"code": locked.code, "reason": reason},
            )
    return locked
