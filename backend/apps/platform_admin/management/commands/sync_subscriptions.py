from django.core.management.base import BaseCommand

from ...services import sync_lifecycle


class Command(BaseCommand):
    help = "Mark overdue subscriptions PAST_DUE, then EXPIRED after the grace days. Schedule daily; safe to repeat."

    def handle(self, *args, **options):
        moved = sync_lifecycle()
        self.stdout.write(f"{moved['past_due']} moved to past due, {moved['expired']} expired.")
