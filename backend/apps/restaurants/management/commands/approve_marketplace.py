"""Approve restaurants for the marketplace from the command line.

New restaurants need the platform owner's approval before they appear (Owner Control Centre > Restaurants > a restaurant). Run this once
after upgrading to keep restaurants that were already listed:

    python manage.py approve_marketplace --already-listed     # everyone who had already switched the marketplace on
    python manage.py approve_marketplace some-restaurant-slug # one restaurant
"""
from django.core.management.base import BaseCommand, CommandError

from apps.restaurants.models import Restaurant


class Command(BaseCommand):
    help = "Approve restaurants for the marketplace (see the module docstring)."

    def add_arguments(self, parser):
        parser.add_argument("slugs", nargs="*", help="Restaurant slugs to approve.")
        parser.add_argument("--already-listed", action="store_true", help="Approve every restaurant that has switched the marketplace on.")

    def handle(self, *args, **options):
        slugs = options["slugs"]
        if not slugs and not options["already_listed"]:
            raise CommandError("Give one or more restaurant slugs, or --already-listed.")
        queryset = Restaurant.objects.filter(marketplace_approved=False)
        queryset = queryset.filter(listed_in_marketplace=True) if options["already_listed"] and not slugs else queryset.filter(slug__in=slugs)
        names = list(queryset.values_list("slug", flat=True))
        queryset.update(marketplace_approved=True)
        self.stdout.write(self.style.SUCCESS(f"Approved {len(names)} restaurant(s): {', '.join(names) or 'none'}"))
