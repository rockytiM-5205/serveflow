"""A new restaurant starts its free trial straight away, on the built-in Free trial plan, so nobody can use ServeFlow without a
subscription clock running. They choose the paid plan they'll buy from Billing. No paid plan needs to exist yet."""
import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.restaurants.models import Restaurant

from .models import Subscription
from .notifications import notify
from .services import start_trial

logger = logging.getLogger(__name__)


def _start(restaurant_id):
    try:
        restaurant = Restaurant.objects.filter(pk=restaurant_id).first()
        if restaurant and not Subscription.objects.filter(restaurant=restaurant).exists():
            start_trial(restaurant)
            notify("signup", f"{restaurant.name} signed up", "Free trial started.", f"#/customers?search={restaurant.slug}", restaurant, f"signup:{restaurant.pk}")
    except Exception:  # noqa: BLE001 - creating a restaurant must never fail because of billing
        logger.exception("Couldn't start the trial for restaurant %s", restaurant_id)


@receiver(post_save, sender=Restaurant, dispatch_uid="platform_admin_auto_trial")
def start_trial_for_new_restaurant(sender, instance, created, **kwargs):
    if created and getattr(settings, "PLATFORM_AUTO_TRIAL", True) and not getattr(instance, "_skip_auto_trial", False):
        transaction.on_commit(lambda: _start(instance.pk))
