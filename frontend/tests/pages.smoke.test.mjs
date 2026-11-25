/* Open each customer page in the fake browser and press its buttons. Catches the "nothing happens" class of bugs:
 * a variable used outside its scope, a null printed as the word "null", a wrong element id. */
import assert from "node:assert/strict";
import test from "node:test";
import { forgetCustomer } from "../customer/js/account-link.js";
import { fakeApi, installDom, tick, until } from "./dom-stub.mjs";

const SLUG = "green-bowl";
const TOKEN = "b".repeat(96);
const NOW = new Date().toISOString();
const LATER = (m) => new Date(Date.now() + m * 60000).toISOString();
const ERR = (status, code, message = "x") => [status, { error: { code, message, details: {} } }];
let run = 0;

function page({ search = "", hash = "", pathname, ids = [], routes = {} }) {
  run += 1;
  const dom = installDom({ search, hash, pathname });
  const { doc, body } = dom;
  const make = (tag, attrs = {}, ...kids) => { const e = doc.createElement(tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); e.append(...kids); return e; };
  const bar = make("div", { class: "container topbar__inner" }, make("a", { id: "brand-link", href: "index.html" }, make("span", { class: "brand__mark" }), make("span", { id: "brand-name" }, "Restaurant")));
  body.append(bar, make("a", { id: "back-link" }), make("div", { id: "content" }), make("div", { id: "live" }));
  for (const [tag, id, attrs] of ids) body.append(make(tag, { id, ...attrs }));
  forgetCustomer();
  const calls = fakeApi(routes);
  return { dom, doc, calls, text: () => doc.body.textContent, byId: (id) => doc.getElementById(id), make,
    button: (label) => doc.body.querySelectorAll("button").find((b) => b.textContent.trim() === label) };
}

const noJunk = (text) => assert.doesNotMatch(text, /\bnull\b|\bundefined\b|\[object/, "a null/undefined leaked onto the page");

// ---------------------------------------------------------------- the order page
const order = (extra = {}) => ({
  reference: "7K#M4@2P", status: "PENDING", payment_status: "UNPAID", fulfilment_type: "PICKUP", table_number: null, pickup_at: LATER(60), pickup_fee: "1.50",
  currency: "USD", subtotal: "10.00", total: "11.50", restaurant: { slug: SLUG, name: "Green Bowl" },
  payment: { amount: "11.50", currency: "USD", reference: "7K#M4@2P", bank_name: "First Bank", account_name: "Mama Put Ltd", account_number: "0123456789", instructions: "Use the reference." },
  review: null, can_review: false, pickup_policy: null, late_fee: null, cancellable: true,
  items: [{ name: "Jollof rice", unit_name: "", unit_price: "5.00", quantity: 2, line_total: "10.00" }], timeline: [{ status: "PENDING", at: NOW }], created_at: NOW, updated_at: NOW, ...extra,
});

async function openOrder(o, extraRoutes = {}) {
  const p = page({ search: `?r=${SLUG}`, hash: `#${TOKEN}`, pathname: "/customer/order.html", routes: { [`GET /orders/${TOKEN}/`]: [200, o], "GET /customers/me/": ERR(401, "not_authenticated"), ...extraRoutes } });
  await import(`../customer/js/order.js?run=${run}`);
  await until(() => p.text().includes("Waiting") || p.text().includes(o.reference), "the order page");
  return p;
}

test("the order page shows the random reference, where to pay and the exact amount", async () => {
  const p = await openOrder(order());
  const text = p.text();
  assert.match(text, /7K#M4@2P/);
  for (const needle of ["Pay now", "First Bank", "Mama Put Ltd", "0123456789", "Use the reference.", "I've paid"]) assert.ok(text.includes(needle), needle);
  assert.match(text, /\$11\.50/);
  noJunk(text);
});

test("pressing I've paid tells the restaurant and the page moves on", async () => {
  const claimed = order({ payment_status: "CLAIMED" });
  const p = await openOrder(order(), { [`POST /orders/${TOKEN}/paid/`]: [200, claimed] });
  p.button("I've paid").click();
  await until(() => p.calls.some((c) => c.path.endsWith("/paid/")), "the claim request");
  await until(() => p.text().includes("Payment sent"), "the page to update");
  noJunk(p.text());
});

test("a late pickup policy is explained on the order page, with the fee when there is one", async () => {
  const policy = { grace_minutes: 15, fee_amount: "100.00", interval_minutes: 15, max_fee: "300.00", free_until: LATER(75), accepted_at: NOW };
  const p = await openOrder(order({ pickup_policy: policy, late_fee: { amount: "200.00", status: "DUE" } }));
  assert.match(p.text(), /Late pickup policy/);
  assert.match(p.text(), /Late fee: \$200\.00/);
  assert.match(p.text(), /Collect by/);
  noJunk(p.text());
});

test("a completed order offers a review, needs a rating, and sends it", async () => {
  const done = order({ status: "COMPLETED", payment_status: "PAID", payment: null, can_review: true, cancellable: false,
    timeline: [{ status: "PENDING", at: NOW }, { status: "COMPLETED", at: NOW }] });
  const reviewed = { ...done, can_review: false, review: { rating: 4, comment: "Hot and tasty", created_at: NOW, status: "PUBLISHED" } };
  const p = await openOrder(done, { [`POST /orders/${TOKEN}/review/`]: [201, reviewed] });
  assert.match(p.text(), /Leave a review/);
  const send = p.button("Send review");
  send.dispatchEvent({ type: "click" });
  p.doc.body.querySelector("form.stack").dispatchEvent({ type: "submit" });
  await tick(20);
  assert.equal(p.calls.filter((c) => c.path.endsWith("/review/")).length, 0, "sent without a rating");
  assert.match(p.text(), /Choose a rating/);
  p.byId("star-4").checked = true;
  p.byId("review-comment").value = "Hot and tasty";
  p.doc.body.querySelector("form.stack").dispatchEvent({ type: "submit" });
  await until(() => p.calls.some((c) => c.path.endsWith("/review/")), "the review request");
  assert.deepEqual(p.calls.find((c) => c.path.endsWith("/review/")).body, { rating: 4, comment: "Hot and tasty" });
  await until(() => p.text().includes("Thanks for your review"), "the thank-you");
  noJunk(p.text());
});

test("a visitor who is not signed in is invited to sign in to review, with no review form", async () => {
  const done = order({ status: "COMPLETED", payment_status: "PAID", payment: null, can_review: false, review_status: "sign_in", cancellable: false,
    timeline: [{ status: "PENDING", at: NOW }, { status: "COMPLETED", at: NOW }] });
  const p = await openOrder(done, {});
  assert.match(p.text(), /Sign in to review/);
  assert.match(p.text(), /Only signed-in customers can leave reviews/);
  assert.doesNotMatch(p.text(), /Send review/);
  assert.equal(p.doc.body.querySelector("textarea"), null);
  noJunk(p.text());
});

test("a customer who has already reviewed this restaurant sees nothing about reviewing on a new order", async () => {
  const done = order({ status: "COMPLETED", payment_status: "PAID", payment: null, can_review: false, review_status: "", review: null, cancellable: false,
    timeline: [{ status: "PENDING", at: NOW }, { status: "COMPLETED", at: NOW }] });
  const p = await openOrder(done, {});
  assert.doesNotMatch(p.text(), /Leave a review|Sign in to review|How was your order|Send review/);
  noJunk(p.text());
});

test("a signed-in customer can add the order to their account", async () => {
  const me = { email: "ada@example.com", first_name: "Ada", last_name: "Obi", phone: "" };
  const p = await openOrder(order(), { "GET /customers/me/": [200, me], "POST /customers/orders/claim/": [200, { reference: "7K#M4@2P" }] });
  await until(() => p.button("Add to my account"), "the add button");
  p.button("Add to my account").click();
  await until(() => p.text().includes("Saved to your account"), "saved message");
  assert.deepEqual(p.calls.find((c) => c.path.endsWith("/claim/")).body, { token: TOKEN });
});

// ---------------------------------------------------------------- customer account pages
test("the account page offers sign in and registration, and signing in goes to the order history", async () => {
  const p = page({ search: "?next=checkout.html%3Fr%3Dgreen-bowl", pathname: "/customer/account.html", routes: {
    "GET /auth/csrf/": [204, null], "GET /customers/me/": ERR(401, "not_authenticated"),
    "POST /customers/login/": [200, { email: "ada@example.com", first_name: "Ada", last_name: "Obi", phone: "" }] } });
  await import(`../customer/js/account.js?run=${run}`);
  await until(() => p.byId("login-email"), "the sign-in form");
  assert.match(p.text(), /Create an account/);
  p.byId("login-email").value = "ada@example.com";
  p.byId("login-password").value = "Tr1cky-Passphrase-9";
  p.doc.body.querySelector("form").dispatchEvent({ type: "submit" });
  await until(() => p.dom.navigations.length, "the redirect");
  assert.equal(p.dom.navigations[0], "checkout.html?r=green-bowl"); // back to where they came from
  noJunk(p.text());
});

test("an unsafe redirect target is ignored", async () => {
  const p = page({ search: "?next=https%3A%2F%2Fevil.example%2F", pathname: "/customer/account.html", routes: {
    "GET /auth/csrf/": [204, null], "GET /customers/me/": ERR(401, "not_authenticated"), "POST /customers/login/": [200, { email: "a@b.c", first_name: "A", last_name: "", phone: "" }] } });
  await import(`../customer/js/account.js?run=${run}`);
  await until(() => p.byId("login-email"));
  p.byId("login-email").value = "a@example.com";
  p.byId("login-password").value = "Tr1cky-Passphrase-9";
  p.doc.body.querySelector("form").dispatchEvent({ type: "submit" });
  await until(() => p.dom.navigations.length);
  assert.equal(p.dom.navigations[0], "my-orders.html");
});

test("a signed-in customer sees their details and can sign out", async () => {
  const me = { email: "ada@example.com", first_name: "Ada", last_name: "Obi", phone: "+2348012345678" };
  const p = page({ pathname: "/customer/account.html", routes: { "GET /auth/csrf/": [204, null], "GET /customers/me/": [200, me], "POST /customers/logout/": [204, null] } });
  await import(`../customer/js/account.js?run=${run}`);
  await until(() => p.text().includes("Ada Obi"), "the profile");
  assert.equal(p.byId("me-first_name").value, "Ada");
  p.button("Sign out").click();
  await until(() => p.dom.navigations.length);
  assert.equal(p.dom.navigations[0], "marketplace.html");
  noJunk(p.text());
});

const history = (over = {}) => ({ public_id: "p1", reference: "7K#M4@2P", status: "PENDING", payment_status: "UNPAID", fulfilment_type: "PICKUP", pickup_at: LATER(60),
  total: "11.50", currency: "USD", created_at: NOW, restaurant: { slug: SLUG, name: "Green Bowl" }, items_count: 2, item_names: ["Jollof rice"], active: true,
  can_review: false, reviewed: false, track_token: TOKEN, ...over });

test("my orders lists what is in progress and earlier orders, each opening its own order page", async () => {
  const done = history({ public_id: "p2", reference: "9X$K2#7M", status: "COMPLETED", active: false, can_review: true });
  const p = page({ pathname: "/customer/my-orders.html", routes: {
    "GET /customers/me/": [200, { email: "a@b.c", first_name: "Ada", last_name: "", phone: "" }],
    "GET /customers/orders/": [200, { next: null, previous: null, results: [history(), done] }],
  } });
  p.calls.length = 0;
  const base = globalThis.fetch;
  globalThis.fetch = (url, init) => base(String(url).includes("active=1") ? "/api/v1/customers/orders/" : url, init);
  await import(`../customer/js/my-orders.js?run=${run}`);
  await until(() => p.text().includes("9X$K2#7M"), "the history");
  assert.match(p.text(), /In progress/);
  assert.match(p.text(), /Leave a review/);
  const links = p.doc.body.querySelectorAll("a").map((a) => a.getAttribute("href")).filter((h) => h?.startsWith("order.html"));
  assert.ok(links.every((h) => h.endsWith(`#${TOKEN}`)), "the order link keeps its token after the #");
  noJunk(p.text());
});

test("my orders asks a signed-out visitor to sign in instead of failing", async () => {
  const p = page({ pathname: "/customer/my-orders.html", routes: { "GET /customers/me/": ERR(401, "not_authenticated") } });
  await import(`../customer/js/my-orders.js?run=${run}`);
  await until(() => p.text().includes("Sign in to see your orders"), "the prompt");
  noJunk(p.text());
});

// ---------------------------------------------------------------- the marketplace and a restaurant page
const card = (over = {}) => ({ slug: SLUG, name: "Green Bowl", description: "Rice and stew", category: { value: "AFRICAN", label: "African" }, area: "Akungba", address: "1 Market Rd",
  logo_url: null, cover_url: null, distance_km: null, availability: "OPEN", is_open_now: null, rating_average: null, rating_count: 0, pickup_enabled: true, dine_in_enabled: true, ...over });

test("the marketplace lists restaurants, shows honest ratings and responds to a search", async () => {
  const ids = [["form", "search-form"], ["input", "q"], ["input", "area"], ["select", "sort"], ["div", "categories"], ["input", "open-now", { type: "checkbox" }],
    ["div", "location-controls"], ["p", "location-note"], ["button", "reset"], ["h2", "results-title"], ["div", "results"], ["button", "more"], ["datalist", "area-list"]];
  const p = page({ pathname: "/customer/marketplace.html", ids, routes: {
    "GET /marketplace/categories/": [200, { results: [{ value: "AFRICAN", label: "African", count: 1 }] }],
    "GET /marketplace/areas/": [200, { results: [{ area: "Akungba", count: 1 }] }],
    "GET /marketplace/restaurants/": [200, { count: 1, page: 1, page_size: 12, has_next: false, results: [card()] }],
    "GET /customers/me/": ERR(401, "not_authenticated"),
  } });
  await import(`../customer/js/marketplace.js?run=${run}`);
  await until(() => p.byId("results").textContent.includes("Green Bowl"), "the results");
  assert.match(p.text(), /No reviews yet/);
  assert.match(p.byId("results-title").textContent, /1 restaurant/);
  p.byId("q").value = "green";
  p.byId("search-form").dispatchEvent({ type: "submit" });
  await tick(30);
  assert.ok(p.calls.some((c) => c.path === "/marketplace/restaurants/"), "searched");
  noJunk(p.text());
});

test("a restaurant page shows its rating, hours and reviews", async () => {
  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, weekday) => ({ weekday, day, periods: weekday < 5 ? [{ opens: "09:00", closes: "17:00" }] : [] }));
  const rest = { slug: SLUG, name: "Green Bowl", description: "Rice", contact_phone: "+2348012345678", address: "1 Market Rd", area: "Akungba", category: { value: "AFRICAN", label: "African" },
    latitude: 7.4, longitude: 5.75, currency: "USD", timezone: "UTC", accepting_orders: true, availability: "OPEN", is_open_now: true, hours: days, rating_average: 4.5, rating_count: 2,
    pickup_enabled: true, pickup_fee: "1.50", pickup_min_minutes: 30, late_policy: null, dine_in_enabled: true, requires_table_number: false, logo_url: null, cover_url: null };
  const p = page({ search: `?r=${SLUG}`, pathname: "/customer/index.html", routes: {
    [`GET /restaurants/${SLUG}/`]: [200, rest],
    [`GET /restaurants/${SLUG}/reviews/`]: [200, { average: 4.5, count: 2, page: 1, page_size: 10, has_next: false,
      results: [{ rating: 5, comment: "Loved it", display_name: "Ada O.", created_at: NOW }, { rating: 4, comment: "", display_name: "Bola A.", created_at: NOW }] }],
    "GET /customers/me/": ERR(401, "not_authenticated"),
  } });
  await import(`../customer/js/home.js?run=${run}`);
  await until(() => p.text().includes("Loved it"), "the reviews");
  assert.match(p.text(), /4\.5 out of 5 from 2 reviews/);
  assert.match(p.text(), /Opening hours/);
  assert.match(p.text(), /Ada O\./);
  noJunk(p.text());
});
