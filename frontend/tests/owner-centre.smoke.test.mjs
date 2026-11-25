/* Owner Control Centre pages (reviews, payments, plans) in the fake browser with a fake platform API. */
import assert from "node:assert/strict";
import test from "node:test";
import { fakeApi, installDom, until } from "./dom-stub.mjs";

const NOW = new Date().toISOString();
const noJunk = (text) => assert.doesNotMatch(text, /\bnull\b|\bundefined\b|\[object/, "a null/undefined leaked onto the page");
const page = (results) => [200, { next: null, previous: null, results }];

async function open(fn, routes) {
  const dom = installDom({ pathname: "/owner-control-centre/index.html" });
  const { doc, body } = dom;
  body.append(doc.createElement("div"));
  const calls = fakeApi(routes);
  const pages = await import("../owner-control-centre/js/pages.js");
  const view = pages[fn]();
  body.append(view.node);
  return { doc, calls, view, text: () => view.node.textContent, button: (label) => view.node.querySelectorAll("button").find((b) => b.textContent.trim() === label) };
}

const review = (over = {}) => ({ id: 5, restaurant_name: "Green Bowl", restaurant_slug: "green-bowl", rating: 2, comment: "Cold food", display_name: "Ada O.", status: "PUBLISHED",
  moderation_reason: "", created_at: NOW, open_reports: [{ reason: "Looks fake to us", reported_at: NOW }], ...over });

test("the reviews page shows reported reviews and hides one only with a reason", async () => {
  const t = await open("reviews", { "GET /platform/reviews/": page([review()]), "POST /platform/reviews/5/hide/": [204, null] });
  await until(() => t.text().includes("Cold food"), "the list");
  assert.match(t.text(), /Looks fake to us/);
  assert.ok(t.button("Dismiss reports"), "no dismiss button");
  noJunk(t.text());
  t.button("Hide").click();
  const dialog = await until(() => t.doc.body.querySelectorAll("dialog").at(-1), "the hide dialog");
  assert.match(dialog.textContent, /reason and your name are kept in the audit log/);
  dialog.querySelectorAll("input").find((i) => (i.getAttribute("id") ?? "").endsWith("reason")).value = "Abusive language";
  dialog.querySelector("form").dispatchEvent({ type: "submit" });
  const call = await until(() => t.calls.find((c) => c.path.endsWith("/hide/")), "the hide request");
  assert.deepEqual(call.body, { reason: "Abusive language" });
});

test("a hidden review offers Restore, not Hide", async () => {
  const t = await open("reviews", { "GET /platform/reviews/": page([review({ status: "HIDDEN", moderation_reason: "Abusive", open_reports: [] })]) });
  await until(() => t.text().includes("Cold food"));
  assert.ok(t.button("Restore"));
  assert.equal(t.button("Hide"), undefined);
  noJunk(t.text());
});

const payment = (over = {}) => ({ id: 9, reference: "SF-PK-1A2B3C4D", kind: "ORDER_PACK", customer_name: "Green Bowl", amount: "500.00", currency: "NGN", status: "AWAITING_CONFIRMATION",
  provider: "BANK_TRANSFER", provider_reference: "", failure_reason: "", transacted_at: NOW, allowed_actions: ["confirm", "fail"], ...over });

test("the payments page labels what each payment is for and can mark one failed with a reason", async () => {
  const t = await open("payments", { "GET /platform/payments/": page([payment(), payment({ id: 10, reference: "SF-UP-1", kind: "UPGRADE", status: "FAILED", failure_reason: "Never arrived", allowed_actions: [] })]),
    "POST /platform/payments/9/fail/": [204, null] });
  await until(() => t.text().includes("SF-PK-1A2B3C4D"), "the list");
  assert.match(t.text(), /Order pack/);
  assert.match(t.text(), /Upgrade/);
  assert.match(t.text(), /Never arrived/);
  noJunk(t.text());
  t.button("Mark failed").click();
  const dialog = await until(() => t.doc.body.querySelectorAll("dialog").at(-1), "the dialog");
  dialog.querySelectorAll("input").find((i) => (i.getAttribute("id") ?? "").endsWith("reason")).value = "Transfer never arrived";
  dialog.querySelector("form").dispatchEvent({ type: "submit" });
  const call = await until(() => t.calls.find((c) => c.path.endsWith("/fail/")), "the fail request");
  assert.deepEqual(call.body, { reason: "Transfer never arrived" });
});

test("the plans page shows the order allowance and the optional order pack", async () => {
  const plan = (id, name, extra = {}) => ({ id, name, description: "", interval: "MONTHLY", price: "3000.00", currency: "NGN", included_orders: 300, included_requests: 1000, rate_limit_per_minute: 60,
    pack_orders: null, pack_price: null, features: [], status: "ACTIVE", is_trial: false, subscribers: 2, ...extra });
  const t = await open("plans", { "GET /platform/plans/": page([plan(2, "Starter", { pack_orders: 50, pack_price: "500.00" }), plan(1, "Free trial", { is_trial: true, price: "0.00" })]) });
  await until(() => t.text().includes("Starter"), "the plans");
  assert.match(t.text(), /Orders included/);
  assert.match(t.text(), /50 for/);
  assert.match(t.text(), /None/);
  noJunk(t.text());
});
