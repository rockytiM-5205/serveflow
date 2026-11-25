/* Click "Place order" in the real checkout script, with a fake browser and a fake server.
 * This is the test that would have caught "the checkout button does nothing". */
import assert from "node:assert/strict";
import test from "node:test";
import { forgetCustomer } from "../customer/js/account-link.js";
import { fakeApi, installDom, tick, until } from "./dom-stub.mjs";

const SLUG = "green-bowl";
const TOKEN = "a".repeat(96);
const LATER = (minutes) => new Date(Date.now() + minutes * 60000).toISOString();

const restaurant = (extra = {}) => ({
  slug: SLUG, name: "Green Bowl", accepting_orders: true, pickup_enabled: true, dine_in_enabled: true, requires_table_number: false,
  pickup_fee: "1.50", pickup_min_minutes: 30, late_policy: null, currency: "USD", timezone: "UTC", logo_url: null, cover_url: null, ...extra,
});
const menu = { restaurant: { currency: "USD" }, categories: [{ id: 1, name: "Mains", items: [{ id: 7, name: "Jollof rice", price: "5.00", is_available: true }] }] };
const slots = { slots: [
  { at: LATER(45), date: "2026-11-09", day: "Today", time: "12:45" }, { at: LATER(60), date: "2026-11-09", day: "Today", time: "13:00" },
  { at: LATER(60 * 24), date: "2026-11-10", day: "Tomorrow", time: "12:00" },
] };

let run = 0;
/** Open checkout.html for a restaurant and return what a person could do on it. */
async function openCheckout({ rest = restaurant(), me = null, slotList = slots } = {}) {
  run += 1;
  const dom = installDom({ search: `?r=${SLUG}`, pathname: "/customer/checkout.html" });
  const { body, doc } = dom;
  const make = (tag, attrs = {}, ...kids) => { const e = doc.createElement(tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); e.append(...kids); return e; };
  body.append(make("a", { id: "brand-link", href: "index.html" }, make("span", { class: "brand__mark" }), make("span", { id: "brand-name" }, "Restaurant")),
    make("a", { id: "back-link", href: "menu.html" }), make("div", { id: "content" }));
  localStorage.setItem(`serveflow.cart.${SLUG}`, JSON.stringify({ v: 1, lines: [[7, 2]] }));
  const calls = fakeApi({
    [`GET /restaurants/${SLUG}/`]: [200, rest],
    [`GET /restaurants/${SLUG}/menu/`]: [200, menu],
    [`GET /restaurants/${SLUG}/pickup-slots/`]: [200, slotList],
    "GET /customers/me/": me ? [200, me] : [401, { error: { code: "not_authenticated", message: "Sign in.", details: {} } }],
    [`POST /restaurants/${SLUG}/checkout/`]: [201, { token: TOKEN, reference: "7K#M4@2P" }],
  });
  forgetCustomer(); // each page load asks the server afresh
  await import(`../customer/js/checkout.js?run=${run}`);
  const form = await until(() => doc.querySelector("form"), "the checkout form");
  const field = (name) => doc.getElementById(`co-${name}`);
  const submit = async () => { form.dispatchEvent({ type: "submit" }); await tick(30); };
  const posts = () => calls.filter((c) => c.method === "POST" && c.path.endsWith("/checkout/"));
  const text = () => doc.getElementById("content").textContent;
  return { dom, doc, field, submit, posts, text, calls, form };
}

function fillDetails(page, { name = "Ada Obi", phone = "+2348012345678" } = {}) {
  page.field("customer_name").value = name;
  page.field("customer_phone").value = phone;
}

test("a pickup order with no late policy is placed when the button is pressed", async () => {
  const page = await openCheckout();
  fillDetails(page);
  await page.submit();
  assert.equal(page.posts().length, 1, "the order was never sent: the button did nothing");
  const body = page.posts()[0].body;
  assert.equal(body.fulfilment_type, "PICKUP");
  assert.match(body.pickup_at, /^\d{4}-\d{2}-\d{2}T/);
  assert.equal(body.accept_late_policy, false);
  assert.deepEqual(body.items, [{ menu_item_id: 7, quantity: 2 }]);
  assert.deepEqual(page.dom.navigations.at(-1), `order.html?r=${SLUG}#${TOKEN}`);
});

test("the total shown includes the pickup fee, and the pay-first note is there", async () => {
  const page = await openCheckout();
  assert.match(page.text(), /Total to pay/);
  assert.match(page.text(), /Total to pay\$11\.50/); // 2 x 5.00 + 1.50: the same amount the server will charge
  assert.doesNotMatch(page.text(), /\bnull\b|undefined/);
  assert.match(page.text(), /bank transfer/);
});

test("with a late pickup policy the customer must accept it before the order is sent", async () => {
  const policy = { grace_minutes: 15, fee_amount: "100.00", interval_minutes: 15, max_fee: "300.00" };
  const page = await openCheckout({ rest: restaurant({ late_policy: policy }) });
  assert.match(page.text(), /late pickup policy/i);
  fillDetails(page);
  await page.submit();
  assert.equal(page.posts().length, 0, "sent without the policy being accepted");
  assert.match(page.doc.getElementById("co-accept_late-error").textContent, /accept the late pickup policy/);
  page.field("accept_late").checked = true;
  await page.submit();
  assert.equal(page.posts().length, 1);
  assert.equal(page.posts()[0].body.accept_late_policy, true);
});

test("a missing name or phone is reported on the field instead of silently doing nothing", async () => {
  const page = await openCheckout();
  await page.submit();
  assert.equal(page.posts().length, 0);
  assert.match(page.doc.getElementById("co-customer_name-error").textContent, /required/);
  fillDetails(page, { phone: "12" });
  await page.submit();
  assert.match(page.doc.getElementById("co-customer_phone-error").textContent, /valid phone/);
});

test("a signed-in customer has their name and phone filled in and is told the order is saved", async () => {
  const page = await openCheckout({ me: { email: "ada@example.com", first_name: "Ada", last_name: "Obi", phone: "+2348012345678" } });
  assert.equal(page.field("customer_name").value, "Ada Obi");
  assert.equal(page.field("customer_phone").value, "+2348012345678");
  assert.match(page.text(), /saved to your account/);
  await page.submit();
  assert.equal(page.posts().length, 1);
});

test("a guest is told they can sign in, and ordering still works", async () => {
  const page = await openCheckout();
  assert.match(page.text(), /Ordering as a guest/);
});

test("with no pickup times the page offers dine in only and the button still works", async () => {
  const page = await openCheckout({ slotList: { slots: [] } });
  assert.equal(page.field("pickup_time"), null);
  fillDetails(page);
  await page.submit();
  assert.equal(page.posts().length, 1);
  assert.equal(page.posts()[0].body.fulfilment_type, "DINE_IN");
  assert.equal(page.posts()[0].body.pickup_at, null);
});

test("a server refusal is shown to the customer", async () => {
  const page = await openCheckout();
  globalThis.fetch = async (url, init) => (init.method === "POST"
    ? new Response(JSON.stringify({ error: { code: "ORDER_LIMIT_REACHED", message: "limit", details: {} } }), { status: 402 })
    : new Response("{}", { status: 404 }));
  fillDetails(page);
  await page.submit();
  assert.match(page.doc.getElementById("content").textContent, /limit|wrong|try again/i);
});
