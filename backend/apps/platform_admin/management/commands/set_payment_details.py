import re

from django.core.management.base import BaseCommand, CommandError

from ...models import PaymentDetails
from ...services import audit


class Command(BaseCommand):
    help = "Set where restaurants send subscription payments (bank transfer). The same fields are editable in the Owner Control Centre."

    def add_arguments(self, parser):
        parser.add_argument("--bank", required=True)
        parser.add_argument("--account-number", required=True)
        parser.add_argument("--account-name", default="")
        parser.add_argument("--note", default="", help="Public note shown on the pricing page. Never put account details here.")

    def handle(self, *args, bank, account_number, account_name, note, **options):
        if not re.fullmatch(r"\d{6,20}", account_number):
            raise CommandError("The account number must be 6 to 20 digits.")
        details = PaymentDetails.objects.first() or PaymentDetails()
        details.bank_name, details.account_number, details.account_name, details.instructions = bank.strip(), account_number, account_name.strip(), note.strip()
        details.save()
        audit(None, "settings.payment_details_updated", "settings", "payment_details", "Payment details changed")
        self.stdout.write(f"Saved. Restaurants will see {details.bank_name} {account_number[:3]}***{account_number[-2:]}.")
