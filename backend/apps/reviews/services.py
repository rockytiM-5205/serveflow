from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.audit.services import record
from apps.common.exceptions import Conflict
from apps.orders.models import Order, OrderStatus
from apps.platform_admin.notifications import notify
from apps.platform_admin.services import audit as platform_audit
from apps.restaurants.models import Restaurant

from .models import Review, ReviewReport


def display_name(full_name):
    """First name and an initial of the last: 'Ada Obi' becomes 'Ada O.'. A review never shows a full name or a phone number."""
    parts = (full_name or "").split()
    if not parts:
        return "Customer"
    first = parts[0][:24]
    return f"{first} {parts[1][0].upper()}." if len(parts) > 1 else first


def refresh_rating(restaurant_id):
    """Recompute a restaurant's rating from its published reviews only. The restaurant row is locked so two reviews arriving at
    once can't leave a stale average, and the number is never typed in by hand."""
    with transaction.atomic():
        Restaurant.objects.select_for_update().get(pk=restaurant_id)
        agg = Review.objects.filter(restaurant_id=restaurant_id, status=Review.Status.PUBLISHED).aggregate(avg=Avg("rating"), n=Count("id"))
        average = Decimal(str(agg["avg"])).quantize(Decimal("0.01")) if agg["n"] else None
        Restaurant.objects.filter(pk=restaurant_id).update(rating_average=average, rating_count=agg["n"])


def create_review(order_id, rating, comment, customer):
    """A review for a COMPLETED order by a signed-in customer. Holding the order's private link proves it was theirs; they may review a
    restaurant once, however many times they order from it. An order not yet in anyone's account joins theirs when they review it."""
    with transaction.atomic():
        order = Order.objects.select_for_update().select_related("restaurant").get(pk=order_id)
        if order.status != OrderStatus.COMPLETED:
            raise Conflict("You can review an order once the restaurant has completed it.", code="not_reviewable", details={"status": order.status})
        if order.customer_id is not None and order.customer_id != customer.pk:
            raise Conflict("This order belongs to a different account.", code="not_your_order")
        if Review.objects.filter(order=order).exists():
            raise Conflict("You have already reviewed this order.", code="already_reviewed")
        if Review.objects.filter(restaurant_id=order.restaurant_id, customer=customer).exists():
            raise Conflict("You have already reviewed this restaurant. Thank you!", code="already_reviewed_restaurant")
        try:
            with transaction.atomic():
                review = Review.objects.create(
                    restaurant=order.restaurant, order=order, customer=customer, rating=rating, comment=comment.strip(),
                    display_name=display_name(order.customer_name),
                )
        except IntegrityError:
            raise Conflict("You have already reviewed this restaurant. Thank you!", code="already_reviewed_restaurant") from None
        if order.customer_id is None:
            order.customer = customer
            order.save(update_fields=["customer"])
        refresh_rating(order.restaurant_id)
        record(restaurant=order.restaurant, actor=None, action="review.created", entity_type="review", entity_id=review.pk,
               metadata={"rating": rating, "order": order.reference})
    return review


def report_review(restaurant, review_id, user, reason):
    """A restaurant asks the platform to look at one of ITS OWN reviews. It cannot change or hide it."""
    reason = (reason or "").strip()
    if not 5 <= len(reason) <= 300:
        raise Conflict("Tell us what is wrong in a few words (5 to 300 characters).", code="reason_required")
    review = get_object_or_404(Review, pk=review_id, restaurant=restaurant)
    try:
        with transaction.atomic():
            report = ReviewReport.objects.create(review=review, restaurant=restaurant, reported_by=user, reason=reason)
            record(restaurant=restaurant, actor=user, action="review.reported", entity_type="review", entity_id=review.pk, metadata={"reason": reason[:100]})
    except IntegrityError:
        raise Conflict("You have already reported this review.", code="already_reported") from None
    notify("review_reported", f"{restaurant.name} reported a review", reason[:200], "#/reviews", restaurant, f"review_report:{report.pk}")
    return report


# ---------------------------------------------------------------- the platform owner's moderation
def hide_review(review_id, actor, reason):
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise Conflict("Give a reason (at least a few words). It is kept in the audit log.", code="reason_required")
    with transaction.atomic():
        review = get_object_or_404(Review.objects.select_for_update().select_related("restaurant"), pk=review_id)
        review.status, review.moderation_reason = Review.Status.HIDDEN, reason[:200]
        review.moderated_by, review.moderated_at = actor, timezone.now()
        review.save(update_fields=["status", "moderation_reason", "moderated_by", "moderated_at"])
        review.reports.filter(status=ReviewReport.Status.OPEN).update(status=ReviewReport.Status.ACTIONED, resolved_at=timezone.now())
        refresh_rating(review.restaurant_id)
        platform_audit(actor, "review.hidden", "review", review.pk, f"{review.restaurant.slug}: {reason[:160]}")
    return review


def restore_review(review_id, actor):
    with transaction.atomic():
        review = get_object_or_404(Review.objects.select_for_update().select_related("restaurant"), pk=review_id)
        review.status, review.moderation_reason = Review.Status.PUBLISHED, ""
        review.moderated_by, review.moderated_at = actor, timezone.now()
        review.save(update_fields=["status", "moderation_reason", "moderated_by", "moderated_at"])
        refresh_rating(review.restaurant_id)
        platform_audit(actor, "review.restored", "review", review.pk, review.restaurant.slug)
    return review


def dismiss_reports(review_id, actor):
    with transaction.atomic():
        review = get_object_or_404(Review.objects.select_related("restaurant"), pk=review_id)
        n = review.reports.filter(status=ReviewReport.Status.OPEN).update(status=ReviewReport.Status.DISMISSED, resolved_at=timezone.now())
        platform_audit(actor, "review.reports_dismissed", "review", review.pk, f"{review.restaurant.slug}: {n} report(s) dismissed")
    return review
