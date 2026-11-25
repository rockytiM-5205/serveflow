"""Menu categories and items. Every row belongs to one restaurant.

Portions are modelled as separate items ("Rice, spoon" and "Rice, plate"), each with its
own price and unit_name. There are no variants. Items are archived, never deleted, so
historical orders (later stage) stay intact.
"""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, URLValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.restaurants.models import Restaurant


class MenuCategory(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="menu_categories")
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, help_text="Inactive categories are hidden from customers.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "menu categories"
        constraints = [
            models.UniqueConstraint(Lower("name"), "restaurant", name="menu_category_unique_name_per_restaurant"),
            # Target for the composite foreign key from MenuItem (see migration 0002).
            models.UniqueConstraint(fields=["id", "restaurant"], name="menu_category_id_restaurant_uniq"),
        ]

    def __str__(self):
        return self.name


def item_image_path(instance, filename):
    return f"restaurants/{instance.restaurant_id}/menu/{filename}"


class DishKind(models.TextChoices):
    """What is drawn for an item on the customer's order plate when it has no photo."""

    RICE = "rice", "Rice or pasta"
    MEAT = "meat", "Meat or chicken"
    FISH = "fish", "Fish or seafood"
    PLANTAIN = "plantain", "Plantain, yam or chips"
    SWALLOW = "swallow", "Swallow (pounded yam, amala, eba)"
    SOUP = "soup", "Soup or stew"
    DRINK = "drink", "Drink"
    DESSERT = "dessert", "Dessert"
    EGG = "egg", "Eggs"
    VEG = "veg", "Salad or vegetables"
    BREAD = "bread", "Bread, snack or pastry"
    DISH = "dish", "Something else"


class MenuItem(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="menu_items")
    category = models.ForeignKey(MenuCategory, on_delete=models.PROTECT, related_name="items")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    unit_name = models.CharField(max_length=32, default="portion", help_text="What one unit is, e.g. spoon, piece, portion.")
    is_available = models.BooleanField(default=True)
    dish_kind = models.CharField(
        max_length=16, blank=True, default="", choices=DishKind.choices,
        help_text="What is drawn for this item on the customer's order plate when it has no photo. Empty: chosen automatically from its name and category.",
    )
    image_url = models.URLField(
        max_length=500,
        null=True,
        blank=True,
        validators=[URLValidator(schemes=["https"])],
        help_text="Older items may have a link to a photo. New photos are uploaded instead (see image).",
    )
    image = models.ImageField(
        upload_to=item_image_path, max_length=200, null=True, blank=True,
        help_text="A photo uploaded from the dashboard (checked and re-encoded as WebP). It is shown instead of image_url.",
    )
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gte=0), name="menu_item_price_non_negative"),
            models.CheckConstraint(
                condition=models.Q(image_url__isnull=True) | models.Q(image_url__regex=r"^https://[^ ]+$"),
                name="menu_item_image_url_https",
            ),
            models.UniqueConstraint(
                Lower("name"),
                "restaurant",
                condition=models.Q(archived_at__isnull=True),
                name="menu_item_unique_active_name_per_restaurant",
            ),
            # Target for the composite foreign key from OrderItem (orders migration 0002).
            models.UniqueConstraint(fields=["id", "restaurant"], name="menu_item_id_restaurant_uniq"),
        ]

    def __str__(self):
        return self.name

    @property
    def is_archived(self):
        return self.archived_at is not None

    def clean(self):
        super().clean()
        if self.category_id and self.restaurant_id and self.category.restaurant_id != self.restaurant_id:
            raise ValidationError({"category": "The category belongs to a different restaurant."})

    def save(self, *args, **kwargs):
        if not self.image_url:
            self.image_url = None  # the CHECK constraint allows NULL or https, never ""
        super().save(*args, **kwargs)

    def archive(self):
        self.archived_at = timezone.now()
        self.save(update_fields=["archived_at", "updated_at"])
