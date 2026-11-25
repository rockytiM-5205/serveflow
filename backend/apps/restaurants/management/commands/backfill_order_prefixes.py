"""Optional and safe to run again: give restaurants that have no order prefix one.

Restaurants get a prefix automatically when they are created or take their next order, and old orders keep the reference they
already have. Run this only if you want every restaurant to show its prefix in Settings straight away.
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.restaurants.models import Restaurant


class Command(BaseCommand):
    help = "Give every restaurant without an order prefix one."

    def handle(self, *args, **options):
        count = 0
        for restaurant in Restaurant.objects.filter(Q(order_prefix__isnull=True) | Q(order_prefix="")):
            restaurant.save(update_fields=["order_prefix"])  # Restaurant.save() assigns a free prefix
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Prefixes added: {count}."))
