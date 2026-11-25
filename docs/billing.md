# Billing: completed orders

ServeFlow bills restaurants by **completed orders per billing period**. API requests are only a technical limit
(per-minute rate limit and the per-key monthly cap), never the billing unit.

## What counts
An order is billable the moment it becomes `COMPLETED` (pickup: collection confirmed; dine-in: served). Submitted,
confirmed, preparing, ready, cancelled, rejected and duplicate (idempotent) requests are never counted. A completed order
that is later refunded stays counted. Marketplace orders and external API orders share one allowance.

Lifecycle: `PENDING -> CONFIRMED -> SERVING (shown as "Preparing") -> READY_FOR_PICKUP -> COMPLETED`.
`READY_FOR_PICKUP` is optional (a kitchen may complete straight from preparing). `REJECTED` and `CANCELLED` are the other
end states. The stored value `SERVING` is kept for compatibility; its label is "Preparing".

## Periods
* A `BillingPeriod` records one period with the plan's allowance, price and rate limit **frozen when it opened**. Editing
  a plan never changes a period that exists.
* Periods follow the subscription anniversary (`Subscription.billing_anchor`), not the calendar month. A subscription that
  starts on Nov 12 runs Nov 12 to Dec 12 (end exclusive); usage resets Dec 12. Every period end is measured from the
  anchor, so a Jan 31 start renews Feb 28 (29 in a leap year), then Mar 31.
* Times are stored in UTC. Anniversaries use the UTC day-of-month; show them in the restaurant's timezone.
* A confirmed payment opens the period it buys. Paying while still paid up starts the next period where the current one
  ends (same anchor). Paying for the first time, after the trial, or after a lapse starts a new period now and resets
  usage. A period still running at that moment is closed early, so periods never overlap.
* Inside the grace window after a lapse (`BILLING_GRACE_DAYS`) orders count against the last period; there is no free reset.

## Ledger and allowance
`OrderUsage` is append-only (no edits or deletes in code), with a database unique constraint on (order, event). Completion
locks the subscription row, so simultaneous completions are counted one after the other. Each row records what paid for it:
`PLAN` (included allowance), `PACK` (an order pack) or `OVERAGE` (an order accepted before the limit and completed after).
New orders are refused when completed orders reach `included + active packs`. Orders already accepted can always be completed.

Refusal looks like (HTTP 402):

```json
{"error": {"code": "ORDER_LIMIT_REACHED",
           "message": "This restaurant has reached its order limit for the current billing period. ...",
           "details": {"action": "upgrade_or_purchase_order_pack", "resets_at": "...", "allowance": 300, "completed_orders": 300}}}
```

Enforcement reads the database inside order creation. The 30-second lock cache is never used for billing decisions.
Retried requests with the same `Idempotency-Key` return the original order and are not blocked by the limit.

## Order packs
`OrderPack` belongs to one billing period, counts only while `ACTIVE`, expires at the end of that period and never
renews. Capacity is used after the plan allowance. `sync_subscriptions` marks expired packs.

A plan can offer a pack (`pack_orders` + `pack_price`, set both or neither, in Plans & Pricing). Buying one:
`POST /api/v1/restaurants/{slug}/billing/order-packs/` (restaurant owner) creates a `PENDING` pack and an
`ORDER_PACK` payment that share one reference (`SF-PK-...`). Nothing is added until the payment is confirmed. One open
pack purchase at a time (asking again returns it). A pack paid for after its period ended is marked `EXPIRED` and flagged
for a refund; it never adds capacity.

## Upgrades and downgrades
Only between plans of the same interval and currency; nothing is prorated by time and no charge is invented.
* **Upgrade (higher price):** the restaurant pays the price difference (an `UPGRADE` payment, `SF-UP-...`). When it is
  confirmed, the *running* period takes the new plan's terms at once: allowance becomes the new plan's (never lower than
  before), the plan name and rate limit are updated, and the change is recorded in `PlanChange` with allowance before and
  after. Usage already recorded stays. The period does not restart.
* **Downgrade (same or lower price):** scheduled for the next anniversary (`PlanChange` + `Subscription.pending_plan`).
  The running period is untouched. The next renewal payment is priced at the new plan; once the period it buys has begun,
  `sync_subscriptions` moves the subscription onto the new plan. Paying late applies it immediately.
* A waiting change can be cancelled (`POST .../billing/plan-change/cancel/`); a waiting upgrade's payment is then failed.
* Not allowed while `PAST_DUE`, between monthly and yearly, or with another change already waiting.

## Payments and webhooks
Every payment is a `SubscriptionPayment` with a `kind`: `SUBSCRIPTION`, `ORDER_PACK` or `UPGRADE`. These are ServeFlow's own
revenue and are never mixed with food-order payments (`orders.Payment`). Revenue reports keep subscription revenue
(renewals and upgrades) apart from order-pack revenue. A payment is confirmed once, only server-side:
* **Bank transfer (default):** the platform owner confirms it; the server checks the amount and currency against the plan,
  pack or upgrade first. The owner can also mark it failed (a reason is required; the actor is audited).
* **Provider webhook:** `POST /api/v1/billing/webhooks/generic/`, signed with `X-Signature: hex(HMAC_SHA256(secret, raw_body))`
  using `PAYMENT_WEBHOOK_SECRET`. With no secret configured the endpoint answers 503 and confirms nothing. Body:
  `{"event_id", "reference", "status": "success"|"failed", "amount", "currency", "provider_reference"}`. A valid signature
  is necessary but not enough: the amount and currency must equal the payment, or nothing happens
  (`amount_mismatch`, audited, owner notified). Each `(provider, event_id)` is stored once in `PaymentWebhookEvent`
  (hash of the body only), so a retry returns `duplicate` and does nothing; a second event for an already confirmed
  payment returns `already_confirmed`. Always answers 200 for authentic events so providers don't retry forever.
* A gateway-specific adapter (Paystack, Flutterwave...) only needs to verify that gateway's signature and translate its
  payload into the shape above.
* A browser success redirect is never treated as proof of payment; there is no endpoint that accepts one.

## Defaults to review
Migration `platform_admin/0003_order_billing` sets the free trial to **30** completed orders per period and leaves every
existing plan at **300**. These are placeholders: set real allowances in Plans & Pricing. Plan prices are untouched.
The monthly per-key API request cap (`included_requests`) is still enforced as a technical limit; decide whether to
raise or remove it.

## Not yet built (later phases)
The owner billing pages and restaurant billing UI for packs and plan changes (the API is ready: see `billing/` in the
restaurant routes and `payments/` with `?kind=` in the platform routes), marketplace, customer accounts, reviews and the
late-pickup policy. Pending pack and upgrade payments don't expire on their own; the owner marks them failed.
