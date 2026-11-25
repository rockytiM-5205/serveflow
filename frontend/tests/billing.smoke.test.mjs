/* The owner's billing page in the fake browser: usage warnings, switching plans any time, buying an order pack. */
import assert from "node:assert/strict";
import test from "node:test";
import { fakeApi, installDom, until } from "./dom-stub.mjs";

const SLUG = "green-bowl";
const NOW = new Date().toISOString();
const LATER = new Date(Date.now() + 20 * 86400000).toISOString();
const noJunk = (text) => assert.doesNotMatch(text, /\bnull\b|\bundefined\b|\[object/, "a null/undefined leaked onto the page");
const plan = (id, name, price, extra = {}) => ({ id, name, description: "", interval: "MONTHLY", price, currency: "NGN", included_orders: 300, included_requests: 1000, rate_limit_per_minute: 60,
  pack_orders: null, pack_price: null, features: ["Dashboard"], status: "ACTIVE", is_trial: false, ...extra });
const PLANS = [plan(2, "Basic", "1500.00"), plan(3, "Starter", "3000.00", { pack_orders: 50, pack_price: "500.00" }), plan(4, "Growth", "9000.00")];
const usage = (over = {}) => ({ period_start: NOW, period_end: LATER, plan_name: "Starter", included_orders: 300, extra_capacity: 0, completed_orders: 120, remaining: 180, percent_used: 40, warning_level: null, limit_reached: false, ...over });

const overview = (over = {}) => ({
  subscription: { status: "ACTIVE", plan: PLANS[1], next_plan: null, plan_to_pay: PLANS[1], current_period_start: NOW, current_period_end: LATER, trial_ends_at: null },
  usage: usage(), pack_offer: { orders: 50, price: "500.00", currency: "NGN", expires_at: LATER }, order_packs: [], pending_plan_change: null, open_extra_payments: [],
  plans: PLANS, payments: [], open_payment: null,
  payment_details: { bank_name: "ServeFlow Bank", account_name: "ServeFlow Ltd", account_number: "0123456789", instructions: "" }, payment_info: { ready: true }, ...over,
});

let run = 0;
async function open(data, extra = {}) {
  run += 1;
  const dom = installDom({ pathname: "/restaurant-dashboard/billing.html" });
  const { doc, body } = dom;
  const make = (tag, attrs = {}, ...kids) => { const e = doc.createElement(tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); e.append(...kids); return e; };
  body.append(make("div", { id: "boot" }), make("div", { id: "app", hidden: "" }, make("nav", { id: "nav" }),
    make("main", { id: "main" }, make("header", { class: "page-head" }, make("p", { id: "restaurant-name" })), make("div", { id: "content" }))));
  const calls = fakeApi({
    "GET /auth/me/": [200, { user: { email: "o@e.c", first_name: "Mama", last_name: "Put" }, memberships: [{ id: 1, role: "OWNER", restaurant: { slug: SLUG, name: "Green Bowl", timezone: "UTC", currency: "NGN" } }], can_create_restaurant: false }],
    [`GET /restaurants/${SLUG}/`]: [200, { slug: SLUG, name: "Green Bowl", currency: "NGN", timezone: "UTC" }],
    [`GET /restaurants/${SLUG}/billing/`]: [200, data], ...extra,
  });
  await import(`../restaurant-dashboard/js/billing.js?run=${run}`);
  await until(() => doc.getElementById("content").textContent.includes("Your subscription"), "the billing page");
  return { doc, calls, text: () => doc.getElementById("content").textContent, button: (label) => doc.body.querySelectorAll("button").find((b) => b.textContent.trim().startsWith(label)) };
}

test("an active restaurant sees how many orders it has used and can buy more", async () => {
  const p = await open(overview());
  assert.match(p.text(), /120 of 300/);
  assert.match(p.text(), /180 left/);
  assert.match(p.text(), /Only completed orders count/);
  assert.ok(p.button("Buy 50 more orders"), "no order pack button");
  noJunk(p.text());
});

test("the page warns at 75, 90 and 100 percent of the orders", async () => {
  for (const [level, words] of [[75, /75%/], [90, /90%/], [100, /reached your order limit/]]) {
    const p = await open(overview({ usage: usage({ warning_level: level, percent_used: level, limit_reached: level === 100, remaining: level === 100 ? 0 : 30 }) }));
    assert.match(p.text(), words, `level ${level}`);
  }
});

test("a restaurant can switch plan at any time: upgrade now, move to a cheaper plan at renewal", async () => {
  const p = await open(overview());
  assert.ok(p.button("Upgrade to Growth"), "no upgrade button");
  assert.ok(p.button("Switch to Basic"), "no switch button");
  assert.match(p.text(), /Pay the .*6,?000.* difference and it starts now/);
  assert.match(p.text(), /Takes effect on/);
  noJunk(p.text());
});

test("pressing a plan button asks the server to change the plan", async () => {
  const p = await open(overview(), { [`POST /restaurants/${SLUG}/billing/subscribe/`]: [201, overview()] });
  p.button("Upgrade to Growth").click();
  const call = await until(() => p.calls.find((c) => c.path.endsWith("/billing/subscribe/")), "the subscribe request");
  assert.deepEqual(call.body, { plan_id: 4 });
});

test("buying an order pack asks the server and the bank details for it are shown once it is pending", async () => {
  const pending = overview({ open_extra_payments: [{ id: 9, reference: "SF-PK-1A2B3C4D", kind: "ORDER_PACK", amount: "500.00", currency: "NGN", status: "AWAITING_CONFIRMATION", provider: "BANK_TRANSFER", created_at: NOW }] });
  const p = await open(overview(), { [`POST /restaurants/${SLUG}/billing/order-packs/`]: [201, { payment: {}, order_pack: {} }] });
  p.button("Buy 50 more orders").click();
  await until(() => p.calls.some((c) => c.path.endsWith("/order-packs/")), "the pack request");
  const q = await open(pending);
  assert.match(q.text(), /SF-PK-1A2B3C4D/);
  assert.match(q.text(), /0123456789/);
  noJunk(q.text());
});

test("a waiting downgrade is shown and can be cancelled", async () => {
  const change = { kind: "DOWNGRADE", to_plan: PLANS[0], effective_at: LATER, amount_due: "0.00" };
  const p = await open(overview({ pending_plan_change: change }), { [`POST /restaurants/${SLUG}/billing/plan-change/cancel/`]: [200, overview()] });
  assert.match(p.text(), /You'll move to Basic/);
  p.button("Cancel this change").click();
  await until(() => p.calls.some((c) => c.path.endsWith("/plan-change/cancel/")), "the cancel request");
  noJunk(p.text());
});

test("an overdue restaurant can still choose a plan", async () => {
  const p = await open(overview({ subscription: { ...overview().subscription, status: "PAST_DUE" } }));
  assert.ok(p.button("Upgrade to Growth") || p.button("Switch to Basic"));
});
