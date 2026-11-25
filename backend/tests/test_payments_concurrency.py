"""The same webhook delivered twice at the same instant (real threads, real connections) activates a pack once."""
import hashlib
import hmac
import json
import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connections
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.platform_admin import usage
from apps.platform_admin.models import OrderPack, PaymentDetails, PaymentWebhookEvent, Plan, Subscription, SubscriptionPayment

pytestmark = pytest.mark.django_db(transaction=True)


def test_two_identical_webhooks_at_once_activate_the_pack_once(settings, shop, make_user, make_membership):
    from apps.platform_admin import billing
    from apps.restaurants.models import MembershipRole

    settings.PAYMENT_WEBHOOK_SECRET = "whsec_concurrency"
    PaymentDetails.objects.create(bank_name="B", account_name="A", account_number="0123456789")
    plan = Plan.objects.create(name="C", interval="MONTHLY", price=Decimal("3000.00"), included_orders=2, included_requests=1000,
                               rate_limit_per_minute=60, pack_orders=5, pack_price=Decimal("500.00"))
    now = timezone.now()
    sub = Subscription.objects.create(restaurant=shop.restaurant, plan=plan, status="ACTIVE", started_at=now, current_period_start=now - timedelta(days=1),
                                      current_period_end=now + timedelta(days=29), billing_anchor=now - timedelta(days=1))
    usage.open_period(sub, plan, sub.current_period_start, sub.current_period_end)
    owner = make_user()
    make_membership(shop.restaurant, owner, MembershipRole.OWNER)
    payment, pack, _ = billing.purchase_order_pack(shop.restaurant, owner)

    raw = json.dumps({"event_id": "evt_same", "reference": payment.reference, "status": "success", "amount": "500.00", "currency": "NGN", "provider_reference": "txn_c"}).encode()
    signature = hmac.new(b"whsec_concurrency", raw, hashlib.sha256).hexdigest()
    results = [None, None]

    def worker(i):
        try:
            results[i] = Client().post(reverse("billing-webhook", kwargs={"provider": "generic"}), data=raw, content_type="application/json", HTTP_X_SIGNATURE=signature).json()
        except Exception as exc:
            results[i] = exc
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert sorted(r["status"] for r in results) == ["duplicate", "processed"], results
    assert PaymentWebhookEvent.objects.count() == 1
    assert OrderPack.objects.get().status == "ACTIVE" and SubscriptionPayment.objects.get().status == "CONFIRMED"
    assert usage.capacity(usage.current_period(sub))["capacity"] == 7
