"""Payment-provider webhooks.

A success redirect in the browser proves nothing. Only a notification whose HMAC-SHA256 signature we can verify with the
shared secret (`PAYMENT_WEBHOOK_SECRET`) may confirm a payment, and even then the amount and currency must match the payment we
created. Each event is recorded once (unique provider + event id), so a provider retrying changes nothing.

The wire format is deliberately provider-neutral ("generic"): a JSON body

    {"event_id": "evt_123", "reference": "SF-PK-1A2B3C4D", "status": "success" | "failed",
     "amount": "3000.00", "currency": "NGN", "provider_reference": "txn_987"}

signed as hex(HMAC_SHA256(secret, raw_body)) in the `X-Signature` header. A gateway-specific adapter (Paystack, Flutterwave...)
only has to translate its own payload into this shape after verifying its own signature.
"""
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.exceptions import Conflict

from . import services
from .models import PaymentWebhookEvent, SubscriptionPayment
from .notifications import notify

PROVIDERS = ("generic",)


class WebhookError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def signature_valid(raw: bytes, header: str) -> bool:
    secret = getattr(settings, "PAYMENT_WEBHOOK_SECRET", "")
    if not secret:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (header or "").strip().lower())


def parse(raw: bytes) -> dict:
    try:
        body = json.loads(raw)
        event_id, reference, status = str(body["event_id"]), str(body["reference"]), str(body["status"]).lower()
        amount, currency = Decimal(str(body["amount"])), str(body["currency"]).upper()
        provider_reference = str(body.get("provider_reference", ""))
    except (ValueError, KeyError, TypeError, InvalidOperation, AttributeError):
        raise WebhookError(400, "invalid_event", "The event body isn't valid.") from None
    if not (0 < len(event_id) <= 100 and 0 < len(reference) <= 64 and len(provider_reference) <= 100 and len(currency) == 3):
        raise WebhookError(400, "invalid_event", "The event body isn't valid.")
    if status not in ("success", "failed"):
        raise WebhookError(400, "invalid_event", "Unknown status.")
    if not amount.is_finite() or amount <= 0:
        raise WebhookError(400, "invalid_event", "The event body isn't valid.")
    return {"event_id": event_id, "reference": reference, "status": status, "amount": amount, "currency": currency, "provider_reference": provider_reference}


def handle(provider: str, raw: bytes, signature: str):
    """Returns (status, outcome). Raises WebhookError for a request that must be refused."""
    if provider not in PROVIDERS:
        raise WebhookError(404, "not_found", "Unknown provider.")
    if not getattr(settings, "PAYMENT_WEBHOOK_SECRET", ""):
        raise WebhookError(503, "webhooks_disabled", "Payment webhooks aren't configured.")
    if not signature_valid(raw, signature):
        raise WebhookError(401, "invalid_signature", "The signature is not valid.")
    event = parse(raw)
    with transaction.atomic():
        try:
            with transaction.atomic():
                record = PaymentWebhookEvent.objects.create(
                    provider=provider, event_id=event["event_id"], payload_sha256=hashlib.sha256(raw).hexdigest(),
                    reference=event["reference"], reported_status=event["status"],
                )
        except IntegrityError:
            return "duplicate", "duplicate"  # already seen: do nothing, tell the provider it's fine
        outcome = _apply(provider, event, record)
        record.outcome, record.processed_at = outcome, timezone.now()
        record.save(update_fields=["outcome", "processed_at", "payment"])
    return "processed", outcome


def _apply(provider, event, record):
    payment = SubscriptionPayment.objects.select_for_update().select_related("subscription__restaurant").filter(reference=event["reference"]).first()
    if payment is None:
        return "unknown_reference"
    record.payment = payment
    if payment.status != SubscriptionPayment.Status.AWAITING_CONFIRMATION:
        return f"already_{payment.status.lower()}"  # confirmed or failed earlier; nothing changes twice
    if event["status"] == "failed":
        services.fail_payment(payment.pk, None, "Declined or failed at the payment provider")
        return "payment_failed"
    if event["currency"] != payment.currency or event["amount"] != payment.amount:
        services.audit(None, "payment.webhook_amount_mismatch", "payment", payment.pk,
                       f"{payment.reference}: provider reported {event['amount']} {event['currency']}, expected {payment.amount} {payment.currency}")
        notify("payment_mismatch", f"A payment for {payment.subscription.restaurant.name} didn't match",
               f"{payment.reference}: the provider reported a different amount. Check it by hand.", "#/payments", payment.subscription.restaurant, f"mismatch:{payment.pk}")
        return "amount_mismatch"
    try:
        with transaction.atomic():
            services.confirm_payment(payment.pk, None, provider_name=SubscriptionPayment.Provider.GATEWAY, provider_reference=event["provider_reference"])
    except IntegrityError:
        return "provider_reference_reused"
    except Conflict as exc:
        return str(exc.get_codes())
    return "confirmed"
