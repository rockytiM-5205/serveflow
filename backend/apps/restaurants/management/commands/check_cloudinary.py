"""Check the Cloudinary connection from your own computer (nothing is uploaded and no secret is printed).

    CLOUDINARY_URL="cloudinary://API_KEY:API_SECRET@CLOUD_NAME" python manage.py check_cloudinary

On Windows PowerShell:  $env:CLOUDINARY_URL="cloudinary://API_KEY:API_SECRET@CLOUD_NAME"; python manage.py check_cloudinary
"""
import os
import re

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Check that CLOUDINARY_URL is well formed and that Cloudinary accepts it."

    def handle(self, *args, **options):
        url = os.environ.get("CLOUDINARY_URL", "").strip()
        if not url:
            raise CommandError("CLOUDINARY_URL is not set in this terminal.")
        if "<" in url or ">" in url:
            raise CommandError("CLOUDINARY_URL contains < or >. Remove them.")
        if url != os.environ.get("CLOUDINARY_URL"):
            self.stdout.write(self.style.WARNING("There are spaces around the value. Remove them."))
        match = re.fullmatch(r"cloudinary://(\d+):([^@:\s]+)@([\w.-]+)", url)
        if not match:
            raise CommandError("CLOUDINARY_URL must look like cloudinary://API_KEY:API_SECRET@CLOUD_NAME (the key is only digits).")
        import cloudinary
        import cloudinary.api

        cloudinary.config(secure=True)
        try:
            cloudinary.api.ping()
        except Exception as exc:  # noqa: BLE001 - show Cloudinary's own reason (it never includes the secret)
            raise CommandError(f"Cloudinary refused the connection: {exc}") from None
        self.stdout.write(self.style.SUCCESS(f"Cloudinary accepted the connection for cloud '{match.group(3)}'."))
