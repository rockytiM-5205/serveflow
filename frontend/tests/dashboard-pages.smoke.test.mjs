/* The restaurant dashboard's Orders and Reviews pages, opened through the real sign-in shell with a fake server. */
import assert from "node:assert/strict";
import test from "node:test";
import { fakeApi, installDom, tick, until } from "./dom-stub.mjs";

const SLUG = "green-bowl";
const NOW = new Date().toISOString();
const noJunk = (text) => assert.doesNotMatch(text, /\bnull\b|\bundefined\b|\[object/, "a null/undefined leaked onto the page");
const session = (role = "OWNER") => ({
  user: { email: "owner@example.com", first_name: "Mama", last_name: "Put" },
  memberships: [{ id: 1, role, restaurant: { slug: SLUG, name: "Green Bowl", timezone: "UTC", currency: "USD" } }], can_create_restaurant: false,
});
const info = { slug: SLUG, name: "Green Bowl", currency: "USD", timezone: "UTC", accepting_orders: true };

const row = (over = {}) => ({
  public_id: "11111111-1111-1111-1111-111111111111", code: "007", reference: "7K#M4@2P", source: "MARKETPLACE", business_date: "2026-11-09", status: "PENDING",
  payment_status: "UNPAID", payment_claimed_at: null, refund_due: false, fulfilment_type: "PICKUP", table_number: null, pickup_at: NOW, pickup_fee: "0.00",
  late_fee: "0.00", late_fee_status: "NONE", late_free_until: null, customer_name: "Ada Obi", items: [{ item_name: "Jollof rice", unit_name: "", unit_price: "5.00", quantity: 2, line_total: "10.00" }],
  total: "10.00", currency: "USD", ready_at: null, completed_at: null, created_at: NOW, updated_at: NOW, ...over,
});

let run = 0;
async function openDashboard(file, routes, role = "OWNER") {
  run += 1;
  const dom = installDom({ pathname: `/restaurant-dashboard/${file}` });
  const { doc, body } = dom;
  const make = (tag, attrs = {}, ...kids) => { const e = doc.createElement(tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); e.append(...kids); return e; };
  body.append(make("div", { id: "boot" }), make("div", { id: "app", hidden: "" }, make("nav", { id: "nav" }), make("main", { id: "main" }, make("header", { class: "page-head" }, make("p", { id: "restaurant-name" })), make("div", { id: "content" }))));
  const calls = fakeApi({ "GET /auth/me/": [200, session(role)], [`GET /restaurants/${SLUG}/`]: [200, info], ...routes });
  await import(`../restaurant-dashboard/js/${file.replace(".html", ".js")}?run=${run}`);
  return { dom, doc, calls, text: () => doc.body.textContent, button: (label) => doc.body.querySelectorAll("button").find((b) => b.textContent.trim() === label), content: () => doc.getElementById("content") };
}

const list = (...rows) => ({ next: null, previous: null, results: rows });

test("the orders page shows the random reference, the staff number and the payment state", async () => {
  const d = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(row())] });
  await until(() => d.text().includes("7K#M4@2P"), "the order card");
  for (const needle of ["#007", "Unpaid", "Confirm order", "Confirm payment", "Find by reference"]) assert.ok(d.text().includes(needle) || d.doc.body.querySelectorAll("input").some((i) => (i.getAttribute("placeholder") ?? "").includes(needle)), needle);
  noJunk(d.text());
});

test("an accepted but unpaid order cannot be started: the staff are shown Confirm payment instead", async () => {
  const d = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(row({ status: "CONFIRMED" }))] });
  await until(() => d.button("Confirm payment"), "the payment button");
  assert.equal(d.button("Start preparing"), undefined, "preparing offered before payment");
  noJunk(d.text());
});

test("confirming payment sends the amount with an idempotency key, and a paid order can be started", async () => {
  const paid = row({ status: "CONFIRMED", payment_status: "PAID" });
  const d = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(row({ status: "CONFIRMED" }))],
    [`POST /restaurants/${SLUG}/orders/11111111-1111-1111-1111-111111111111/payment/`]: [200, paid] });
  (await until(() => d.button("Confirm payment"))).click();
  const dialog = await until(() => d.doc.body.querySelectorAll("dialog").at(-1), "the payment dialog"); // the last one: the account sheet is the first
  assert.match(dialog.textContent, /Only confirm when the money has arrived/);
  dialog.querySelector("form").dispatchEvent({ type: "submit" });
  const call = await until(() => d.calls.find((c) => c.path.endsWith("/payment/")), "the payment request");
  assert.deepEqual(call.body, { method: "TRANSFER", amount: "10.00", reference: "" });
  assert.ok(call.headers && (call.headers["Idempotency-Key"] || call.headers.get?.("Idempotency-Key")), "no idempotency key");
});

test("a paid order is started with the Start preparing button", async () => {
  const d = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(row({ status: "CONFIRMED", payment_status: "PAID" }))],
    [`POST /restaurants/${SLUG}/orders/11111111-1111-1111-1111-111111111111/transitions/`]: [200, row({ status: "SERVING", payment_status: "PAID" })] });
  (await until(() => d.button("Start preparing"))).click();
  const call = await until(() => d.calls.find((c) => c.path.endsWith("/transitions/")), "the transition");
  assert.equal(call.body.to_status, "SERVING");
});

test("a completed order with a late fee shows it and lets staff mark it collected", async () => {
  const late = row({ status: "COMPLETED", payment_status: "PAID", late_fee: "200.00", late_fee_status: "DUE" });
  const d = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(late)],
    [`POST /restaurants/${SLUG}/orders/11111111-1111-1111-1111-111111111111/late-fee/`]: [200, { ...late, late_fee_status: "PAID" }] });
  await until(() => d.text().includes("Late fee to collect"), "the late-fee notice");
  d.button("Late fee collected").click();
  const call = await until(() => d.calls.find((c) => c.path.endsWith("/late-fee/")), "the settle request");
  assert.deepEqual(call.body, { action: "paid", reason: "" });
  noJunk(d.text());
});

test("a staff member cannot waive a late fee, a manager can see the button", async () => {
  const late = row({ status: "COMPLETED", payment_status: "PAID", late_fee: "200.00", late_fee_status: "DUE" });
  const staff = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(late)] }, "STAFF");
  await until(() => staff.button("Late fee collected"));
  assert.equal(staff.button("Waive late fee"), undefined);
  const manager = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(late)] }, "MANAGER");
  await until(() => manager.button("Waive late fee"), "the waive button");
});

test("a paid order that was cancelled warns the restaurant to refund the customer", async () => {
  const d = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(row({ status: "CANCELLED", payment_status: "PAID", refund_due: true }))] });
  await until(() => d.text().includes("refund"), "the refund notice");
  noJunk(d.text());
});

test("searching by reference sends the search to the server", async () => {
  const d = await openDashboard("orders.html", { [`GET /restaurants/${SLUG}/orders/`]: [200, list(row())] });
  await until(() => d.text().includes("7K#M4@2P"));
  const form = d.doc.body.querySelector("form[role=search]") ?? d.doc.body.querySelectorAll("form").find((f) => f.querySelector("input[type=search]"));
  form.querySelector("input").value = "7K#M4@2P";
  const before = d.calls.length;
  form.dispatchEvent({ type: "submit" });
  await until(() => d.calls.length > before, "the search request");
  assert.equal(d.calls.at(-1).path, `/restaurants/${SLUG}/orders/`);
});

test("the reviews page lists reviews and lets a manager report one (but not staff)", async () => {
  const review = { id: 5, rating: 2, comment: "Cold food", display_name: "Ada O.", status: "PUBLISHED", order_reference: "7K#M4@2P", open_reports: 0, created_at: NOW };
  const routes = { [`GET /restaurants/${SLUG}/reviews/inbox/`]: [200, { next: null, previous: null, results: [review] }],
    [`GET /restaurants/${SLUG}/reviews/`]: [200, { average: 2, count: 1, page: 1, page_size: 1, has_next: false, results: [] }],
    [`POST /restaurants/${SLUG}/reviews/5/report/`]: [204, null] };
  const manager = await openDashboard("reviews.html", routes, "MANAGER");
  await until(() => manager.text().includes("Cold food"), "the review");
  assert.match(manager.text(), /2\.0 out of 5 from 1 review/);
  manager.button("Report this review").click();
  const dialog = await until(() => manager.doc.body.querySelectorAll("dialog").at(-1), "the report dialog");
  dialog.querySelector("textarea").value = "Not a real customer";
  dialog.querySelector("form").dispatchEvent({ type: "submit" });
  const call = await until(() => manager.calls.find((c) => c.path.endsWith("/report/")), "the report");
  assert.deepEqual(call.body, { reason: "Not a real customer" });
  noJunk(manager.text());
  const staff = await openDashboard("reviews.html", routes, "STAFF");
  await until(() => staff.text().includes("Cold food"));
  assert.equal(staff.button("Report this review"), undefined);
});

test("an empty reviews page says so plainly", async () => {
  const d = await openDashboard("reviews.html", { [`GET /restaurants/${SLUG}/reviews/inbox/`]: [200, { next: null, previous: null, results: [] }],
    [`GET /restaurants/${SLUG}/reviews/`]: [200, { average: null, count: 0, page: 1, page_size: 1, has_next: false, results: [] }] });
  await until(() => d.text().includes("No reviews yet"), "the empty state");
  noJunk(d.text());
});
