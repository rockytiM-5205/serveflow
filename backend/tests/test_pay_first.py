"""Random order references, pickup times and fees, the restaurant's account details, and paying before preparing."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.orders.models import Order, OrderStatus, Payment, generate_reference
from apps.restaurants.models import MembershipRole, OpeningPeriod, PaymentAccount

pytestmark = pytest.mark.django_db

MONDAY_10_07 = datetime(2026, 11, 9, 10, 7, tzinfo=dt_timezone.utc)


def later(**delta):
    return (timezone.now() + timedelta(**delta)).isoformat()


def code(response):
    return response.json()["error"]["code"]


def url(name, shop, order=None, **kwargs):
    kw = {"slug": shop.restaurant.slug, **kwargs}
    if order is not None:
        kw["public_id"] = order.public_id
    return reverse(name, kwargs=kw)


def move(api_client, shop, order, to_status):
    return api_client.post(url("staff-order-transition", shop, order), {"to_status": to_status}, format="json")


def confirm_payment(api_client, shop, order, key="k" * 20):
    return api_client.post(url("staff-order-payment", shop, order), {"method": "TRANSFER", "amount": str(order.total)}, format="json", HTTP_IDEMPOTENCY_KEY=key)


# ---------------------------------------------------------------- the random reference
def test_references_are_random_readable_and_contain_a_symbol():
    references = {generate_reference() for _ in range(400)}
    assert len(references) == 400
    for reference in references:
        assert len(reference) == 8
        assert any(c in "@#$%&*!" for c in reference) and any(c.isdigit() for c in reference) and any(c.isalpha() for c in reference)
        assert not set(reference) & set("01ILO")  # nothing that looks like something else


def test_customers_get_the_reference_never_the_staff_number(place, shop):
    body = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    assert "code" not in body and body["reference"] == Order.objects.get().reference
    assert Order.objects.get().code == "001"  # staff still have the short number for the kitchen


def test_staff_can_find_an_order_by_its_reference(api_client, shop, place, staff_login):
    first = place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460001").json()
    place(shop.restaurant, [(shop.rice.pk, 1)], phone="+442079460002")
    staff_login(shop.restaurant, MembershipRole.STAFF)
    for term in (first["reference"], first["reference"].lower()):  # symbols and all, any letter case
        found = api_client.get(url("staff-orders", shop), {"search": term}).json()["results"]
        assert [o["reference"] for o in found] == [first["reference"]]
    assert api_client.get(url("staff-orders", shop), {"search": "0001"}).json()["results"][0]["customer_name"] == "Ada"  # phone ending


# ---------------------------------------------------------------- pickup time and fee
def test_a_pickup_order_needs_a_time(place, shop):
    response = place(shop.restaurant, [(shop.rice.pk, 1)], pickup_at=None)
    assert response.status_code == 400 and "pickup_at" in response.json()["error"]["details"]
    assert not Order.objects.exists()


@pytest.mark.parametrize("delta, accepted", [
    ({"minutes": -10}, False), ({"minutes": 10}, False), ({"minutes": 20}, False),
    ({"minutes": 35}, True), ({"hours": 5}, True), ({"hours": 47}, True), ({"hours": 49}, False),
])
def test_pickup_is_at_least_thirty_minutes_ahead_and_within_two_days(place, shop, delta, accepted):
    response = place(shop.restaurant, [(shop.rice.pk, 1)], pickup_at=later(**delta))
    assert response.status_code == (201 if accepted else 400), response.content
    if accepted:
        assert Order.objects.get().pickup_at is not None


def test_pickup_must_fall_inside_the_published_opening_hours(place, shop, monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: MONDAY_10_07)
    OpeningPeriod.objects.create(restaurant=shop.restaurant, weekday=0, opens="09:00", closes="17:00")
    at = lambda day, hour: datetime(2026, 11, day, hour, 0, tzinfo=dt_timezone.utc).isoformat()  # noqa: E731
    assert place(shop.restaurant, [(shop.rice.pk, 1)], pickup_at=at(9, 12)).status_code == 201
    for closed in (at(9, 18), at(10, 12)):  # after closing, and a day with no hours
        response = place(shop.restaurant, [(shop.rice.pk, 1)], pickup_at=closed, phone="+442079460777")
        assert response.status_code == 400 and "closed" in response.json()["error"]["details"]["pickup_at"][0]


def test_the_pickup_fee_is_added_by_the_server_and_frozen_on_the_order(place, shop):
    shop.restaurant.pickup_fee = Decimal("1.50")
    shop.restaurant.save()
    body = place(shop.restaurant, [(shop.rice.pk, 2)], pickup_fee="0.00", total="1.00").json()  # client values are ignored
    assert (body["subtotal"], body["pickup_fee"], body["total"]) == ("5.00", "1.50", "6.50")
    shop.restaurant.pickup_fee = Decimal("9.00")  # a later change never touches an order already placed
    shop.restaurant.save()
    order = Order.objects.get()
    assert (order.pickup_fee, order.total) == (Decimal("1.50"), Decimal("6.50"))


def test_dine_in_has_no_pickup_time_and_no_fee(place, shop):
    shop.restaurant.pickup_fee = Decimal("1.50")
    shop.restaurant.save()
    body = place(shop.restaurant, [(shop.rice.pk, 2)], fulfilment_type="DINE_IN", table_number="4", pickup_at=later(hours=1)).json()
    assert (body["pickup_at"], body["pickup_fee"], body["total"]) == (None, "0.00", "5.00")


def test_the_slots_start_thirty_minutes_ahead_on_a_fifteen_minute_grid(api_client, shop, monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: MONDAY_10_07)
    body = api_client.get(url("public-pickup-slots", shop)).json()
    slots = body["slots"]
    assert (body["minimum_minutes"], body["pickup_fee"]) == (30, "0.00")
    assert slots[0]["time"] == "10:45" and slots[0]["day"] == "Today"
    assert slots[-1]["time"] == "22:00" and len(slots) == 46  # no published hours: only the next 12 hours are offered
    assert all(int(s["time"][-2:]) % 15 == 0 for s in slots)


def test_the_slots_follow_the_opening_hours_and_every_slot_can_be_ordered(api_client, shop, place, monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: MONDAY_10_07)
    OpeningPeriod.objects.create(restaurant=shop.restaurant, weekday=0, opens="09:00", closes="17:00")
    slots = api_client.get(url("public-pickup-slots", shop)).json()["slots"]
    assert (slots[0]["time"], slots[-1]["time"], len(slots)) == ("10:45", "16:45", 25)
    for slot in (slots[0], slots[-1]):
        assert place(shop.restaurant, [(shop.rice.pk, 1)], pickup_at=slot["at"], phone=f"+4420794{slot['time'][:2]}000").status_code == 201


# ---------------------------------------------------------------- the restaurant's account
def account_url(shop):
    return reverse("restaurant-payment-account", kwargs={"slug": shop.restaurant.slug})


ACCOUNT = {"bank_name": "First Bank", "account_name": "Mama Put Ltd", "account_number": "0123456789", "instructions": "Use the reference as narration."}


def test_the_owner_sets_the_account_and_the_audit_log_never_records_the_number(api_client, make_restaurant, staff_login):
    shop = type("S", (), {"restaurant": make_restaurant(with_account=False)})
    staff_login(shop.restaurant, MembershipRole.OWNER)
    assert api_client.get(account_url(shop)).json()["ready"] is False
    response = api_client.put(account_url(shop), ACCOUNT, format="json")
    assert response.status_code == 200 and response.json()["ready"] is True
    assert api_client.get(account_url(shop)).json()["account_number"] == "0123456789"
    entry = AuditLog.objects.get(action="restaurant.payment_account_changed")
    assert "0123456789" not in str(entry.metadata)


def test_only_the_owner_changes_the_account_but_staff_can_read_it(api_client, shop, staff_login, make_restaurant):
    staff_login(shop.restaurant, MembershipRole.MANAGER)
    assert api_client.put(account_url(shop), ACCOUNT, format="json").status_code == 403
    staff_login(shop.restaurant, MembershipRole.STAFF)
    assert api_client.get(account_url(shop)).status_code == 200
    other = type("S", (), {"restaurant": make_restaurant()})
    assert api_client.get(account_url(other)).status_code == 403  # not their restaurant


@pytest.mark.parametrize("override", [{"account_number": "12"}, {"account_number": "12-34-56"}, {"bank_name": ""}, {"account_name": "  "}])
def test_account_details_are_validated(api_client, shop, staff_login, override):
    staff_login(shop.restaurant, MembershipRole.OWNER)
    assert api_client.put(account_url(shop), {**ACCOUNT, **override}, format="json").status_code == 400


def test_a_restaurant_cannot_start_taking_orders_without_an_account(api_client, make_restaurant, staff_login, place, make_category, make_item):
    restaurant = make_restaurant(with_account=False)
    staff_login(restaurant, MembershipRole.OWNER)
    settings_url = reverse("restaurant-settings", kwargs={"slug": restaurant.slug})
    refused = api_client.patch(settings_url, {"accepting_orders": True}, format="json")
    assert refused.status_code == 400 and "accepting_orders" in refused.json()["error"]["details"]
    item = make_item(make_category(restaurant))
    type(restaurant).objects.filter(pk=restaurant.pk).update(accepting_orders=True)  # even if it was somehow switched on
    blocked = place(restaurant, [(item.pk, 1)])
    assert blocked.status_code == 409 and code(blocked) == "payment_details_missing" and not Order.objects.exists()
    PaymentAccount.objects.create(restaurant=restaurant, **{k: v for k, v in ACCOUNT.items()})
    assert api_client.patch(settings_url, {"accepting_orders": True}, format="json").status_code == 200
    assert place(restaurant, [(item.pk, 1)]).status_code == 201


# ---------------------------------------------------------------- paying before preparing
def test_the_customer_is_shown_exactly_how_to_pay(place, shop, api_client):
    shop.restaurant.pickup_fee = Decimal("0.50")
    shop.restaurant.save()
    created = place(shop.restaurant, [(shop.rice.pk, 2)]).json()
    assert created["payment"] == {
        "amount": "5.50", "currency": "USD", "reference": created["reference"], "bank_name": "Test Bank",
        "account_name": "Test Kitchen", "account_number": "0123456789", "instructions": "",
    }
    again = api_client.get(reverse("public-order", kwargs={"token": created["token"]})).json()
    assert again["payment"]["reference"] == created["reference"]


def test_preparing_cannot_start_until_payment_is_confirmed(api_client, shop, order_in, staff_login):
    order = order_in("CONFIRMED")
    staff_login(shop.restaurant, MembershipRole.STAFF)
    refused = move(api_client, shop, order, "SERVING")
    assert refused.status_code == 409 and code(refused) == "payment_required"
    order.refresh_from_db()
    assert order.status == "CONFIRMED"
    assert confirm_payment(api_client, shop, order).status_code == 200
    assert move(api_client, shop, order, "SERVING").status_code == 200
    assert Payment.objects.get().method == "TRANSFER"


def test_confirming_the_order_does_not_need_payment_but_preparing_does(api_client, shop, order_in, staff_login):
    order = order_in()
    staff_login(shop.restaurant, MembershipRole.STAFF)
    assert move(api_client, shop, order, "CONFIRMED").status_code == 200  # accepting is separate from being paid
    assert code(move(api_client, shop, order, "SERVING")) == "payment_required"


def test_i_have_paid_flags_the_order_but_never_starts_preparing(api_client, shop, place, staff_login):
    created = place(shop.restaurant, [(shop.rice.pk, 2)]).json()
    paid_url = reverse("public-order-paid", kwargs={"token": created["token"]})
    first = api_client.post(paid_url)
    assert first.status_code == 200 and first.json()["payment_status"] == "CLAIMED" and first.json()["payment"] is not None
    claimed_at = Order.objects.get().payment_claimed_at
    again = api_client.post(paid_url)
    assert again.status_code == 200 and Order.objects.get().payment_claimed_at == claimed_at  # saying it twice changes nothing
    assert AuditLog.objects.filter(action="payment.claimed").count() == 1

    order = Order.objects.get()
    staff_login(shop.restaurant, MembershipRole.STAFF)
    Order.objects.filter(pk=order.pk).update(status=OrderStatus.CONFIRMED)
    assert code(move(api_client, shop, order, "SERVING")) == "payment_required"  # a claim is not proof

    assert confirm_payment(api_client, shop, order).status_code == 200  # staff checked the bank
    api_client.logout()
    after = api_client.get(reverse("public-order", kwargs={"token": created["token"]})).json()
    assert after["payment_status"] == "PAID" and after["payment"] is None  # nothing left to pay


def test_a_bad_token_or_a_closed_order_cannot_be_claimed(api_client, shop, place, order_in):
    assert api_client.post(reverse("public-order-paid", kwargs={"token": "0" * 96})).status_code == 404
    created = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    Order.objects.update(status=OrderStatus.REJECTED)
    response = api_client.post(reverse("public-order-paid", kwargs={"token": created["token"]}))
    assert response.status_code == 409 and code(response) == "not_payable"


def test_a_customer_cannot_cancel_an_order_they_have_paid_for(api_client, shop, place):
    created = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    api_client.post(reverse("public-order-paid", kwargs={"token": created["token"]}))
    lookup = api_client.get(reverse("public-order", kwargs={"token": created["token"]})).json()
    assert lookup["cancellable"] is False
    response = api_client.post(reverse("public-order-cancel", kwargs={"token": created["token"]}))
    assert response.status_code == 409 and code(response) == "paid_order"


def test_cancelling_a_paid_order_is_flagged_for_a_refund(api_client, shop, order_in, staff_login):
    order = order_in("CONFIRMED")
    staff_login(shop.restaurant, MembershipRole.MANAGER)
    confirm_payment(api_client, shop, order)
    response = api_client.post(url("staff-order-cancel", shop, order), {"reason": "Out of stock"}, format="json")
    assert response.status_code == 200 and response.json()["refund_due"] is True
    assert AuditLog.objects.filter(action="order.refund_due").count() == 1
    unpaid = order_in("CONFIRMED", phone="+442079460555")
    other = api_client.post(url("staff-order-cancel", shop, unpaid), {"reason": "Changed mind"}, format="json").json()
    assert other["refund_due"] is False and AuditLog.objects.filter(action="order.refund_due").count() == 1


def test_the_staff_queue_shows_who_has_said_they_paid(api_client, shop, place, staff_login):
    created = place(shop.restaurant, [(shop.rice.pk, 1)]).json()
    api_client.post(reverse("public-order-paid", kwargs={"token": created["token"]}))
    staff_login(shop.restaurant, MembershipRole.STAFF)
    rows = api_client.get(url("staff-orders", shop), {"payment_status": "CLAIMED"}).json()["results"]
    assert [r["reference"] for r in rows] == [created["reference"]] and rows[0]["payment_claimed_at"] is not None
