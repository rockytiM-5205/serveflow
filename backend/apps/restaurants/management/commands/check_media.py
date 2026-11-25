"""Find pictures the database points to but that are missing from disk (and, optionally, forget them so pages fall back cleanly).

    python manage.py check_media            # list them
    python manage.py check_media --clear    # also empty the missing picture fields

A restaurant logo, cover or dish photo whose file has gone (a moved or restored media folder, a different DJANGO_MEDIA_ROOT, an old upload)
shows as a broken image. The pages now cope with that, but this tells you which ones to upload again.
"""
from django.core.management.base import BaseCommand

from apps.menu.models import MenuItem
from apps.restaurants.models import Restaurant


def missing(field_file):
    if not field_file:
        return False
    try:
        return not field_file.storage.exists(field_file.name)
    except Exception:  # noqa: BLE001 - a storage we can't ask counts as unknown, not missing
        return False


class Command(BaseCommand):
    help = "List (and optionally clear) picture references whose files are missing."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="empty the picture fields whose files are missing")

    def handle(self, *args, clear=False, **options):
        found = 0
        for restaurant in Restaurant.objects.all():
            for field in ("logo", "cover"):
                if missing(getattr(restaurant, field)):
                    found += 1
                    self.stdout.write(f"{restaurant.name} ({restaurant.slug}): {field} file is missing: {getattr(restaurant, field).name}")
                    if clear:
                        setattr(restaurant, field, None)
                        restaurant.save(update_fields=[field])
        for item in MenuItem.objects.select_related("restaurant").exclude(image=""):
            if missing(item.image):
                found += 1
                self.stdout.write(f"{item.restaurant.name}: menu item '{item.name}' photo is missing: {item.image.name}")
                if clear:
                    item.image = None
                    item.save(update_fields=["image"])
        self.stdout.write(self.style.SUCCESS(f"{found} missing picture(s)." + (" Cleared." if clear and found else "")))
