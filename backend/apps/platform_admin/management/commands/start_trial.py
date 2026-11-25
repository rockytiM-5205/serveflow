from django.core.management.base import BaseCommand, CommandError

from apps.common.exceptions import Conflict
from apps.restaurants.models import Restaurant

from ...models import Plan
from ...services import start_trial


class Command(BaseCommand):
    help = "Start a free trial for a restaurant on a plan (the trial length comes from BILLING_TRIAL_DAYS, default 14)."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="Restaurant account ID (slug).")
        parser.add_argument("--plan", help="The paid plan they intend to buy (id or exact name). Optional: every trial runs on the free trial plan.")
        parser.add_argument("--days", type=int, help="Override the trial length.")

    def handle(self, *args, slug, plan=None, days=None, **options):
        restaurant = Restaurant.objects.filter(slug=slug).first()
        if restaurant is None:
            raise CommandError(f"No restaurant with slug {slug!r}.")
        found = None
        if plan:
            found = Plan.objects.filter(pk=int(plan)).first() if plan.isdigit() else Plan.objects.filter(name=plan).first()
            if found is None:
                raise CommandError(f"No plan {plan!r}. Create one in the Owner Control Centre first.")
        try:
            subscription = start_trial(restaurant, found, days=days)
        except Conflict as err:
            raise CommandError(str(err.detail)) from err
        self.stdout.write(f"Free trial started for {slug}, ending {subscription.trial_ends_at:%Y-%m-%d}.")
