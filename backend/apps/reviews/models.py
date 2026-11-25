"""Customer reviews. A review hangs off ONE completed order: only a signed-in customer who really ordered and had the order completed
can write one, each order can be reviewed once, and each customer can review a restaurant only once (however many times they order).
Restaurants cannot edit or delete a review; they can only report it, and the platform owner decides whether to hide it."""
from django.conf import settings
from django.db import models


class Review(models.Model):
    class Status(models.TextChoices):
        PUBLISHED = "PUBLISHED", "Published"
        HIDDEN = "HIDDEN", "Hidden by moderation"

    restaurant = models.ForeignKey("restaurants.Restaurant", on_delete=models.PROTECT, related_name="reviews")
    order = models.OneToOneField("orders.Order", on_delete=models.PROTECT, related_name="review")  # one review per order, enforced by the database
    customer = models.ForeignKey(
        "customers.CustomerProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews",
        help_text="Who wrote it. Empty only for reviews written before reviews needed an account.",
    )
    rating = models.PositiveSmallIntegerField()
    comment = models.CharField(max_length=1000, blank=True)
    display_name = models.CharField(max_length=60, help_text="First name and an initial, e.g. Ada O. Never the phone number.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PUBLISHED)
    moderation_reason = models.CharField(max_length=200, blank=True)
    moderated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    moderated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="reviews_review_rating_1_to_5"),
            models.CheckConstraint(condition=models.Q(status__in=["PUBLISHED", "HIDDEN"]), name="reviews_review_status_valid"),
            models.UniqueConstraint(fields=["customer", "restaurant"], condition=models.Q(customer__isnull=False), name="reviews_one_per_customer_restaurant"),
        ]
        indexes = [models.Index(fields=["restaurant", "status", "-created_at"], name="reviews_restaurant_idx")]

    def __str__(self):
        return f"{self.rating}/5 for {self.restaurant.slug}"


class ReviewReport(models.Model):
    """A restaurant asking the platform to look at a review (abusive, not about their food, not a real customer...)."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        DISMISSED = "DISMISSED", "Dismissed"
        ACTIONED = "ACTIONED", "Review hidden"

    review = models.ForeignKey(Review, on_delete=models.PROTECT, related_name="reports")
    restaurant = models.ForeignKey("restaurants.Restaurant", on_delete=models.PROTECT, related_name="+")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["review", "reported_by"], name="reviews_report_once_per_person"),
            models.CheckConstraint(condition=models.Q(status__in=["OPEN", "DISMISSED", "ACTIONED"]), name="reviews_report_status_valid"),
        ]
