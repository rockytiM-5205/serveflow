# ServeFlow API guide

How the API works, how to call it well, and how to size what a plan should allow. For every endpoint and field see
[api.md](api.md) and the interactive reference at `/api/v1/docs/`. This guide is about *using* it.

## 1. Who calls what

| Caller | How they identify | Typical calls |
|---|---|---|
| **Diners** (your own website or app, or ServeFlow's pages) | Nothing: customer routes are public | `GET /restaurants/{slug}/menu/`, `POST /restaurants/{slug}/checkout/`, `GET /orders/{token}/` |
| **Restaurant staff** | Session cookie + CSRF (the dashboard) | Orders queue, menu edits, billing |
| **An integration** (a server that uses ServeFlow for a restaurant) | **API key**: `Authorization: Bearer sf_live_…` | The same restaurant routes, with limits and usage tracked per key |

A key is optional on customer routes today: without one a call works exactly as before. With one, the call is checked
and counted against that key's limits.

## 2. The ordering flow in three calls

```bash
# 1. Read the menu (prices are decimal strings; never trust a price you cached longer than a minute or two)
curl -H "Authorization: Bearer $SF_KEY" https://YOUR-HOST/api/v1/restaurants/green-bowl/menu/

# 2. Place the order. Send ids and quantities only: the server prices it.
#    Make ONE Idempotency-Key per order attempt (16-64 letters, digits, - or _).
curl -X POST https://YOUR-HOST/api/v1/restaurants/green-bowl/checkout/ \
  -H "Authorization: Bearer $SF_KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: 7f3a9c2e-order-0001" \
  -d '{"customer_name":"Ada","customer_phone":"08012345678","fulfilment_type":"PICKUP",
       "items":[{"menu_item_id":12,"quantity":2}]}'
# 201 returns the order and a "token"

# 3. Follow it. The token is the credential: keep it private.
curl https://YOUR-HOST/api/v1/orders/$TOKEN/
```

Status flow: `PENDING → CONFIRMED → SERVING → SERVED` (or `REJECTED` / `CANCELLED`). Payment is separate:
`UNPAID → PAID`, recorded by staff after `SERVED`.

## 3. API keys

- **Where they come from:** the ServeFlow owner creates them in the Owner Control Centre (API Management). The secret is
  shown once, so copy it then. Restaurants can't create their own yet.
- **Keep them on a server.** Never put a key in a web page, mobile app or public repository. Anyone holding it can use your
  allowance.
- **Environments:** `live` keys work normally. `test` keys can read but never change data (`403 test_key_read_only`); there
  is no sandbox for placing test orders yet.
- **One restaurant per key.** Using it on another restaurant's path returns `403 api_key_wrong_restaurant`.
- **Revoking** a key stops it immediately (`401 invalid_api_key`). Create a new one and swap it in.
- Each key carries two numbers, copied from the restaurant's plan when it is created and adjustable by ServeFlow:
  a **per-minute rate limit** and a **monthly request allowance**.

## 4. Limits, and what counts as a request

**Plan limits (per key).** Two numbers per plan: requests per minute and requests per month. Read the current numbers
from the live plan list, not from this document: `GET /api/v1/billing/plans/` returns `rate_limit_per_minute` and
`included_requests` for every plan. Go over and you get:

| Situation | Status and code | What to do |
|---|---|---|
| Over the per-minute limit | `429 rate_limited`, header `Retry-After` (seconds) | Wait that long, then retry |
| Over the monthly allowance | `429 monthly_quota_exceeded` | Stop, and ask ServeFlow to raise the allowance or move plan |
| Bad, unknown or revoked key | `401 invalid_api_key` | Check the key; it may have been revoked |
| Subscription ended | `402 subscription_inactive` | The restaurant needs to pay; show a "paused" message |

**What counts toward a key's monthly allowance:** every call you make **with the key** to a restaurant route
(`/restaurants/{slug}/…`): menu, restaurant info, checkout. Failed calls count too (a 404 or a validation error still used a
request), and so does a retry. An idempotent replay counts as a request.

**What does not count:**
- `GET /orders/{token}/` and `POST /orders/{token}/cancel/` have no restaurant in the URL, so they are not tied to a key,
  not counted against the allowance, and not limited by it. They have their own protection of 600 per minute per IP.
- Staff dashboard traffic (session cookie, no key). It does show in ServeFlow's usage pages, so don't be surprised that
  a restaurant's total is larger than its key's count. A dashboard tab refreshes the order queue every 5 seconds, which is
  roughly 8,600 requests a day for one tab open for 12 hours.

**Built-in protections that apply whatever the plan** (so large integrations should know them): 30 checkouts per minute per
IP, 20 orders per hour per phone number per restaurant, and at most 3 pending orders per phone per restaurant. A server that
sends all its diners' orders from one IP shares that single 30-per-minute budget.

## 5. Sizing: how many requests should a plan allow?

These are **worked examples, not ServeFlow's plan limits** (your plans aren't decided). Adjust the assumptions to your
restaurants, then set each plan's two numbers in Plans & Pricing.

Counted requests per month ≈ menu reads + checkouts (+ restaurant info reads, if you make them).

| Size of restaurant | Orders per day | With the menu cached 60 s | Without caching (about 10 menu reads per order) |
|---|---|---|---|
| Small | 30 | 22,500 | 9,900 |
| Medium | 150 | 26,100 | 49,500 |
| Large | 500 | 36,600 | 165,000 |

How the table is worked out: a cached integration reads the menu once a minute for a 12-hour day (720 a day, 21,600 a month),
plus one checkout per order (30 × orders per day). An uncached one reads the menu about 10 times per order (browsers who
don't buy included) plus the checkout, so 11 × orders per day × 30.

**Suggested starting allowances** (about 2 to 3 times the uncached figure, so a busy month doesn't lock anyone out):

| Plan size | Monthly allowance | Per-minute limit |
|---|---|---|
| Small | 25,000 | 60 |
| Medium | 100,000 | 120 |
| Large | 300,000 | 300 |

The per-minute number only needs to cover the busiest minute. For a large restaurant in a lunch rush (say 100 orders an hour
and 18 counted requests a minute uncached), 300 leaves plenty of room. Raise the numbers if you add endpoints that integrations
poll.

## 6. Making requests the best way

1. **Cache the menu** for 30 to 60 seconds. It is your biggest source of counted requests, and prices rarely change by the minute.
2. **One `Idempotency-Key` per order attempt.** Reuse the same key when you retry that attempt after a timeout or a 5xx, and a
   dropped connection can never place the order twice. Make a new key for a genuinely new order. The same key with a different
   body is `409 idempotency_key_reused`.
3. **Retry only what is safe to retry:** network errors, 5xx, and 429 (after `Retry-After`). Use exponential backoff with a bit
   of random jitter. Never retry 400, 401, 403, 404 or 409 unchanged.
4. **Don't poll an order faster than every 15 to 30 seconds**, and stop as soon as it reaches `SERVED`, `REJECTED` or
   `CANCELLED`. ServeFlow's own pages poll every 5 seconds from a browser, which is fine for one person but heavy from a server
   tracking many diners.
5. **Never trust client prices.** Send item ids and quantities only; show the `total` the server returns.
6. **Handle `402`** by showing a friendly "ordering is paused" message. It means the restaurant's trial or subscription ended.
7. **Keep order tokens private.** Don't log them or put them in URLs you share; they are the only thing that identifies an order
   to a diner.
8. **Set timeouts** (5 to 10 seconds) on every call, and log the `error.code` from failures, not just the status.

## 7. Trial and subscription behaviour (what your integration will see)

- A new restaurant gets a **2-day free trial** the moment it is created.
- When the trial ends the restaurant **stops working at once**: customers get `402`, and staff can still look at their
  dashboard but can't change anything. There is no grace period after a trial.
- The restaurant pays by bank transfer from **Billing** in its dashboard, using the reference shown there. When ServeFlow
  confirms the transfer it works again immediately.
- A paid subscription that isn't renewed gets **3 grace days**, then locks the same way.
- Suspended restaurants return `404` on public routes.

## 8. Errors at a glance

Every error has the shape `{"error": {"code": "...", "message": "...", "details": {}}}`. Branch on `code`, never on the message.

| Status | Codes you may meet |
|---|---|
| 400 | `validation_error` (field errors in `details`), `malformed_request` |
| 401 | `invalid_api_key`, `not_authenticated` |
| 402 | `subscription_inactive` |
| 403 | `api_key_wrong_restaurant`, `test_key_read_only`, `insufficient_role`, `csrf_failed` |
| 404 | `not_found` (also suspended restaurants and bad order tokens) |
| 409 | `idempotency_key_reused`, `not_accepting_orders`, `item_unavailable`, `too_many_open_orders` |
| 429 | `rate_limited`, `monthly_quota_exceeded`, `throttled` (with `Retry-After`) |

## 9. Not available yet

Webhooks (you must poll for status), self-service keys for restaurants, a sandbox for test orders, per-endpoint limits, a usage
endpoint for restaurants to see their own count, and key authentication for order tracking by token.
