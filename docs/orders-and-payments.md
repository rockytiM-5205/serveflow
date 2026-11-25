# Orders, payments and pickup

## The order reference
Every restaurant has its own **order prefix** (3 to 5 capitals or digits, unique across the platform, made from its name and editable in Settings until its first order). Customers see a reference made of that prefix and **5 random characters**, such as `PRM-8K29P` (letters and digits, no look-alikes like 0, O, 1, I, L; no symbols, because banks often strip them from a narration). Orders made before the prefix existed keep their older 8-character reference such as `7K#M4@2P`, which works exactly as before. The old rules below applied to that older kind (letters, digits and at least one symbol from `@ # $ % & * !`;
no look-alike characters like 0, O, 1, I, L). They quote it as the bank-transfer narration and when they collect. It names an
order; it is **not** a secret and opens nothing: only the signed order link does. The short daily number (`#042`) still exists
for the kitchen and is shown to staff only, never to customers. Staff find an order with the search box on the Orders page
(reference, just the random end of one such as `8K29P`, customer name, or the last digits of a phone number; `?search=` in the API).

## Customers pay before anything is prepared
1. The customer places the order (no account) and is shown the restaurant's bank details, the exact amount and the reference.
2. They transfer the money, then tap **I've paid**. That only flags the order (`payment_status: CLAIMED`); it never starts preparing.
3. Staff check their bank, then **Confirm payment** (`PAID`). Only then can the order go to *Preparing*
   (`409 payment_required` otherwise, for every order type: pickup and dine-in alike).
4. Accepting an order (`CONFIRMED`) does not need payment; preparing does.
5. If a **paid** order is rejected or cancelled the order carries `refund_due: true`, the dashboard shows a refund notice and
   the audit log records `order.refund_due`. ServeFlow never holds the money, so the restaurant refunds the customer itself.
6. A customer can't cancel an order once they have said they paid (`paid_order`); they contact the restaurant.

**Confirming many at once.** On the Orders page, **Payments to check** lists every open order whose customer tapped *I've paid*. Staff
tick the orders whose money they can see in their bank (or **Select all**) and press **Confirm payments**; one request
(`POST /api/v1/restaurants/<slug>/orders/payments/confirm/`, up to 50 at a time) records each as a bank transfer for its full total, with
the order's reference as the bank reference. An order that is already paid, rejected or cancelled is skipped and the rest go through.
Each payment is still audited with the staff member's name.

## Busy hours
For a rush (ten customers a minute) nobody should click through every order one at a time.
* **Accept new orders automatically** (Settings, a switch; off by default, manager or owner): every new order is accepted the moment it
  arrives (history shows *Accepted automatically*, by System). It never skips the payment rule: nothing is prepared until the money is confirmed.
* **Tick, then act.** Every open order on the Orders page has a tick box. **Select all**, then use the buttons that appear for what is
  ticked: *Paid: confirm and start preparing*, *Confirm payments only*, *Accept*, *Start preparing*, *Mark ready*, *Complete*. A paid order
  that is still pending is accepted on the way to preparing. Orders that can't take the step (for example not paid yet) are skipped and
  the screen says how many and why; the rest go through.
* `POST /api/v1/restaurants/<slug>/orders/transitions/` `{orders: [...], to_status: CONFIRMED|SERVING|READY_FOR_PICKUP|COMPLETED}` (up to 50
  at a time) does the moving; the payments call above takes `start_preparing: true` to pay and start in one request. Every step is the same
  status change as pressing the single button, so the history, the audit log and the billing of completed orders are unchanged.

`ServeFlow` does not check bank transfers automatically. "Customer says paid" is a hint, never proof.

## The restaurant's account
Settings, **Payments** card (owner edits, staff can read): bank, account name, account number, an optional note. A restaurant
**cannot switch on orders until these are filled in** (`400` on the settings change, `409 payment_details_missing` when
ordering). `GET/PUT /api/v1/restaurants/<slug>/payment-account/`. The audit log notes that it changed, never the number.

## Pickup time and fee
* Pickup orders need `pickup_at`: at least **30 minutes** ahead (a 5-minute allowance for a customer still filling in the
  form), within 48 hours, and while the restaurant is open if it published hours.
* `GET /api/v1/restaurants/<slug>/pickup-slots/` lists the choices: every 15 minutes from 30 minutes ahead; with no published
  hours only the next 12 hours are offered. It also returns the restaurant's pickup fee.
* **Pickup fee:** each restaurant sets a small fee (Settings, Payments, *Pickup fee*; 0 = none) in its own currency. The server
  adds it to pickup orders only, shows it before the customer orders, and freezes it on the order (`orders.pickup_fee`);
  the database enforces `total = subtotal + pickup_fee`. Clients can't set it.
* Settings (`config/settings/base.py`): `PICKUP_MIN_LEAD_MINUTES` (30), `PICKUP_LEAD_SLACK_MINUTES` (5), `PICKUP_SLOT_MINUTES` (15),
  `PICKUP_MAX_HOURS` (48).

## Late pickup policy
Each restaurant decides whether to charge customers who collect late (Settings, Payments, *Late pickup policy*; off by default):
free minutes after the order is ready, a fee per interval, the interval, and a maximum per order.
* **Seen and accepted first:** the rules appear in the restaurant's public details; for a pickup order the customer must tick that they
  accept them (`accept_late_policy: true`, else `400`). The rules are copied onto the order, so a later change never alters it.
* **The restaurant's delay is never charged:** the clock starts only when staff mark the order **Ready**, at the later of that moment and the
  pickup time the customer chose. No Ready mark, no fee. Dine-in orders are never charged.
* **Worked out once, at collection:** when the order is completed, fee = fee per interval times each full or part interval after the free period,
  never above the maximum. It is a separate amount from what was paid up front (`late_fee`, `late_fee_status` DUE).
* **Settled by staff, audited:** *Late fee collected* (any staff) or *Waive* (manager or owner, reason required). Events: `order.late_fee_due`,
  `order.late_fee_paid`, `order.late_fee_waived`. Orders with a fee due stay in the staff "Needs attention" queue.
* The customer's order page shows the rules, when the free period ends once the order is ready, and any fee and its status.

## Plans: switching any time
A restaurant can ask to change plan at any time. A dearer plan on the same interval is an **upgrade** (pay the difference, it
starts now). Anything else (cheaper, monthly/yearly, another currency) is **scheduled for the next renewal** so what was paid
for isn't taken away. Overdue restaurants simply have their next payment priced at the plan they pick. Asking again replaces
a waiting change; choosing the current plan cancels it. See [billing.md](billing.md).

## Pictures not showing in development
Uploaded pictures are saved under `MEDIA_ROOT` and served at `/media/`. Django only served them when `DEBUG` was on, and
development keeps `DEBUG` off by default, so they were saved but showed as broken. `config/settings/development.py` now sets
`SERVE_MEDIA_FILES = True`, which serves them without `DEBUG`. Production still serves `MEDIA_ROOT` from the web server.
