// Pure helper tests. Run from the frontend/ folder with: node --test
import assert from "node:assert/strict";
import test from "node:test";

import { isHttpsUrl, isValidEmail, isValidPrice, isValidSlug, isValidSortOrder, slugify } from "../shared/js/validators.js";
import { parseSlug, telHref } from "../customer/js/helpers.js";
import { safeNext } from "../restaurant-dashboard/js/session.js";

test("parseSlug accepts well-formed slugs and lowercases them", () => {
  assert.equal(parseSlug("?r=green-bowl"), "green-bowl");
  assert.equal(parseSlug("?r=Green-Bowl"), "green-bowl");
  assert.equal(parseSlug("?x=1&r=abc"), "abc");
});

test("parseSlug rejects missing or malformed slugs", () => {
  for (const search of ["", "?r=", "?r=ab", "?r=-bad", "?r=bad-", "?r=a--b", "?r=has space", "?r=a/b", "?r=../x", `?r=${"a".repeat(64)}`]) {
    assert.equal(parseSlug(search), null, search);
  }
});

test("telHref only ever builds a tel: link from digits and plus", () => {
  assert.equal(telHref("+44 (0)20 7946-0958"), "tel:+4402079460958");
  assert.equal(telHref("javascript:alert(1)"), "tel:1");
  assert.equal(telHref("call us"), null);
  assert.equal(telHref(""), null);
  assert.equal(telHref(null), null);
});

test("isHttpsUrl", () => {
  assert.ok(isHttpsUrl("https://cdn.example.com/a.jpg"));
  for (const bad of ["http://a.com/x.jpg", "javascript:alert(1)", "data:image/png;base64,AA", "//a.com/x.jpg", "https://", "", null, undefined, 5]) {
    assert.ok(!isHttpsUrl(bad), String(bad));
  }
});

test("isValidPrice matches what the backend accepts", () => {
  for (const ok of ["0", "5", "2.5", "12.50", "99999999.99"]) assert.ok(isValidPrice(ok), ok);
  for (const bad of ["", "-1", "1.234", "abc", "1,5", "123456789", ".5", "5.", " 5"]) assert.ok(!isValidPrice(bad), bad);
});

test("isValidSortOrder", () => {
  assert.ok(isValidSortOrder(0) && isValidSortOrder(32767));
  for (const bad of [-1, 32768, 1.5, NaN, null]) assert.ok(!isValidSortOrder(bad), String(bad));
});

test("safeNext knows the menu page", () => {
  assert.equal(safeNext("menu.html"), "menu.html");
  assert.equal(safeNext("https://evil.example"), "index.html");
});

test("slugify produces valid slugs", () => {
  assert.equal(slugify("Green Bowl & Grill"), "green-bowl-grill");
  assert.equal(slugify("  Café Délice!  "), "cafe-delice");
  assert.equal(slugify("---"), "");
  assert.equal(slugify("a".repeat(100)).length, 63);
  assert.ok(!slugify(`${"a".repeat(62)} b`).endsWith("-"));
  for (const name of ["Green Bowl", "Mama's Kitchen #2", "Ünïcode Eats"]) assert.ok(isValidSlug(slugify(name)), name);
});

test("isValidSlug and isValidEmail", () => {
  assert.ok(isValidSlug("green-bowl") && isValidSlug("abc"));
  for (const bad of ["ab", "-a-", "a--b", "Ab c", "a_b", "", null]) assert.ok(!isValidSlug(bad), String(bad));
  assert.ok(isValidEmail("a@b.co"));
  for (const bad of ["a@b", "a b@c.co", "@b.co", "", null]) assert.ok(!isValidEmail(bad), String(bad));
});

test("safeNext knows the new pages", () => {
  assert.equal(safeNext("settings.html"), "settings.html");
  assert.equal(safeNext("create-restaurant.html"), "create-restaurant.html");
});

// ---- cart, ordering helpers ----
import { clampQuantity, createCart, describeCart, fromCents, idempotencyKeyFor, loadLastOrder, saveLastOrder, toCents } from "../customer/js/cart.js";
import { HEADLINE, isTerminal, timelineSteps, tokenFromHash } from "../customer/js/order-view.js";
import { formatClock, timeAgo } from "../restaurant-dashboard/js/time.js";

const fakeStorage = () => {
  const data = new Map();
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, String(v)), removeItem: (k) => data.delete(k), data };
};

test("money is handled in whole cents, never floats", () => {
  assert.equal(toCents("2.50"), 250);
  assert.equal(toCents("0.10"), 10);
  assert.equal(toCents("7"), 700);
  assert.equal(toCents("19.9"), 1990);
  assert.equal(toCents("abc"), 0);
  assert.equal(fromCents(250), "2.50");
  assert.equal(fromCents(5), "0.05");
  assert.equal(fromCents(toCents("0.10") * 3), "0.30"); // 0.1 * 3 would be 0.30000000000000004 as a float
});

test("quantities are clamped to 0-99", () => {
  assert.deepEqual([clampQuantity(5), clampQuantity(-3), clampQuantity(500), clampQuantity("x"), clampQuantity(2.9)], [5, 0, 99, 0, 2]);
});

test("the cart keeps ids and quantities, survives reloads and ignores corrupt storage", () => {
  const storage = fakeStorage();
  const cart = createCart("green-bowl", storage);
  cart.change(7, 1);
  cart.change(7, 1);
  cart.set(9, 3);
  assert.equal(cart.quantity(7), 2);
  assert.equal(cart.count(), 5);
  assert.deepEqual(JSON.parse(storage.data.get("serveflow.cart.green-bowl")), { v: 1, lines: [[7, 2], [9, 3]] });
  assert.equal(createCart("green-bowl", storage).count(), 5); // a new page load
  assert.equal(createCart("other-place", storage).count(), 0); // carts are per restaurant

  cart.change(7, -5);
  assert.equal(cart.quantity(7), 0);
  assert.equal(cart.entries().length, 1);

  for (const junk of ["not json", '{"v":2,"lines":[]}', '{"v":1,"lines":[["x",1],[3,"y"],[-1,2],[4,0],[5,9999]]}']) {
    const s = fakeStorage();
    s.setItem("serveflow.cart.p", junk);
    assert.ok(createCart("p", s).count() <= 99, junk);
  }
});

test("the cart is capped at 99 per item", () => {
  const cart = createCart("p", fakeStorage());
  cart.set(1, 98);
  cart.change(1, 5);
  assert.equal(cart.quantity(1), 99);
});

test("reconcile drops items that are gone or unavailable", () => {
  const cart = createCart("p", fakeStorage());
  cart.set(1, 1); cart.set(2, 1); cart.set(3, 1);
  const menu = new Map([[1, { id: 1, is_available: true }], [2, { id: 2, is_available: false }]]);
  assert.deepEqual(cart.reconcile(menu).sort(), [2, 3]);
  assert.deepEqual(cart.entries(), [[1, 1]]);
});

test("the estimated total uses menu prices", () => {
  const cart = createCart("p", fakeStorage());
  cart.set(1, 3); cart.set(2, 2);
  const menu = new Map([[1, { id: 1, price: "2.50" }], [2, { id: 2, price: "1.25" }]]);
  const { lines, totalCents } = describeCart(cart, menu);
  assert.equal(totalCents, 1000);
  assert.deepEqual(lines.map((l) => l.lineCents), [750, 250]);
});

test("cart subscribers are told about changes", () => {
  const cart = createCart("p", fakeStorage());
  let calls = 0;
  const off = cart.subscribe(() => calls++);
  cart.set(1, 1); cart.clear();
  off(); cart.set(1, 1);
  assert.equal(calls, 2);
});

test("the last order token is only remembered when it looks like a token", () => {
  const s = fakeStorage();
  saveLastOrder("p", "0".repeat(96), s);
  assert.equal(loadLastOrder("p", s), "0".repeat(96));
  saveLastOrder("p", "nonsense", s);
  assert.equal(loadLastOrder("p", s), null);
});

test("a retried order reuses its idempotency key; a changed order gets a new one", () => {
  const s = fakeStorage();
  const order = { items: [{ menu_item_id: 1, quantity: 2 }], customer_name: "Ada" };
  const first = idempotencyKeyFor("p", order, s);
  assert.match(first, /^[A-Za-z0-9_-]{16,64}$/);
  assert.equal(idempotencyKeyFor("p", { ...order }, s), first);
  assert.notEqual(idempotencyKeyFor("p", { ...order, customer_name: "Bo" }, s), first);
});

test("order links come only from a well-formed fragment", () => {
  const token = "ab".repeat(48);
  assert.equal(tokenFromHash(`#${token}`), token);
  for (const bad of ["", "#", "#short", `#${token}0`, `#${token.toUpperCase()}`, null]) assert.equal(tokenFromHash(bad), null, String(bad));
});

test("the order timeline follows the status", () => {
  const order = (status, reached) => ({ status, timeline: reached.map((s) => ({ status: s })) });
  const steps = timelineSteps(order("SERVING", ["PENDING", "CONFIRMED", "SERVING"]));
  assert.deepEqual(steps.map((s) => [s.done, s.current]), [[true, false], [true, false], [true, true], [false, false], [false, false]]);
  const cancelled = timelineSteps(order("CANCELLED", ["PENDING", "CANCELLED"]));
  assert.ok(cancelled.every((s) => !s.current));
  assert.ok(isTerminal("COMPLETED") && isTerminal("REJECTED") && !isTerminal("PENDING"));
  for (const status of ["PENDING", "CONFIRMED", "SERVING", "READY_FOR_PICKUP", "COMPLETED", "REJECTED", "CANCELLED"]) assert.ok(HEADLINE[status], status);
});

test("time wording", () => {
  const now = Date.parse("2026-10-26T12:00:00Z");
  assert.equal(timeAgo("2026-10-26T11:59:40Z", now), "just now");
  assert.equal(timeAgo("2026-10-26T11:55:00Z", now), "5 min ago");
  assert.equal(timeAgo("2026-10-26T09:00:00Z", now), "3 h ago");
  assert.equal(timeAgo("2026-10-24T12:00:00Z", now), "2 d ago");
  assert.equal(timeAgo("garbage", now), "just now");
  assert.equal(formatClock("2026-10-26T12:05:00Z", "UTC", "en-GB"), "12:05");
  assert.equal(formatClock("2026-10-26T12:05:00Z", "Not/AZone", "en-GB"), "");
});

// ---- marketplace ----
import { CATEGORIES } from "../shared/js/categories.js";
import { buildPeriods, coordinateText, formatDay, parseDay } from "../restaurant-dashboard/js/hours-format.js";
import {
  apiQuery, distanceLabel, locationProblem, mapsHref, periodsText, ratingLabel, stateFromUrl, todayIndex, urlFromState,
} from "../customer/js/marketplace-helpers.js";

test("distanceLabel is short and honest", () => {
  assert.equal(distanceLabel(0.18), "180 m");
  assert.equal(distanceLabel(0.004), "10 m");
  assert.equal(distanceLabel(2.449), "2.4 km");
  assert.equal(distanceLabel(23.6), "24 km");
  for (const bad of [null, undefined, NaN, -1, "3"]) assert.equal(distanceLabel(bad), "");
});

test("ratingLabel never invents a rating", () => {
  assert.equal(ratingLabel(null, 0), "No reviews yet");
  assert.equal(ratingLabel(5, 0), "No reviews yet");
  assert.equal(ratingLabel(4.46, 12), "4.5 (12 reviews)");
  assert.equal(ratingLabel(4, 1), "4.0 (1 review)");
});

test("the address bar keeps filters but never a location", () => {
  const state = stateFromUrl("?q=%20mama%20&area=Ikare&category=pizza&open=1&sort=rating&radius=5&lat=7.4&lng=5.7");
  assert.deepEqual(state, { q: "mama", area: "Ikare", category: "PIZZA", openNow: true, sort: "rating", radius: 5 });
  assert.equal(urlFromState(state), "?q=mama&area=Ikare&category=PIZZA&open=1&sort=rating&radius=5");
  assert.ok(!urlFromState(state).includes("lat"));
  assert.equal(urlFromState(stateFromUrl("")), "");
});

test("stateFromUrl ignores nonsense", () => {
  const state = stateFromUrl("?sort=popular&radius=-3&category=" + "x".repeat(60));
  assert.equal(state.sort, "");
  assert.equal(state.radius, 0);
  assert.equal(state.category.length, 20);
});

test("apiQuery only sends a location when we have one, and distance sorting needs it", () => {
  const base = { q: "", area: "", category: "", openNow: false, sort: "", radius: 0 };
  assert.equal(apiQuery(base, null), "");
  assert.equal(apiQuery({ ...base, q: "mama", openNow: true }, null, 2), "q=mama&open_now=true&page=2");
  const near = apiQuery({ ...base, radius: 10 }, { lat: 7.4000123, lng: 5.75 });
  assert.equal(near, "lat=7.40001&lng=5.75000&radius_km=10");
  assert.equal(apiQuery({ ...base, sort: "distance" }, null), ""); // would be a 400: no location to sort by
  assert.equal(apiQuery({ ...base, radius: 10 }, null), ""); // a radius means nothing without a location
});

test("locationProblem explains each failure and always offers area search", () => {
  for (const code of [1, 2, 3]) assert.match(locationProblem(code), /area|settings/);
  assert.match(locationProblem(1), /blocked/);
});

test("periodsText and todayIndex", () => {
  assert.equal(periodsText([]), "Closed");
  assert.equal(periodsText([{ opens: "09:00", closes: "14:00" }, { opens: "17:00", closes: "22:00" }]), "09:00\u201314:00, 17:00\u201322:00");
  const sundayLateUtc = new Date("2026-11-08T23:30:00Z"); // Sunday in UTC, already Monday in Lagos
  assert.equal(todayIndex("UTC", sundayLateUtc), 6);
  assert.equal(todayIndex("Africa/Lagos", sundayLateUtc), 0);
  assert.equal(todayIndex("Not/AZone", sundayLateUtc) >= 0, true); // an unknown zone never throws
});

test("mapsHref needs both coordinates", () => {
  assert.equal(mapsHref(7.4, 5.75), "https://www.google.com/maps/search/?api=1&query=7.4,5.75");
  assert.equal(mapsHref(null, 5.75), null);
});

test("opening hours text round-trips and rejects mistakes", () => {
  assert.equal(formatDay([{ opens: "09:00", closes: "14:00" }, { opens: "17:00", closes: "22:00" }]), "09:00-14:00, 17:00-22:00");
  assert.deepEqual(parseDay(""), { periods: [] });
  assert.deepEqual(parseDay("9:00-14:00 , 17:00\u201322:00").periods, [{ opens: "09:00", closes: "14:00" }, { opens: "17:00", closes: "22:00" }]);
  for (const bad of ["9am-5pm", "09:00", "17:00-09:00", "09:00-12:00, 11:00-15:00", "25:00-26:00"]) assert.ok(parseDay(bad).error, bad);
  const built = buildPeriods(["09:00-17:00", "", "", "", "", "10:00-12:00, 13:00-23:00", ""]);
  assert.deepEqual(built.periods.map((p) => p.weekday), [0, 5, 5]);
  assert.deepEqual(buildPeriods(["", "bad", "", "", "", "", ""]), { day: 1, error: "Write times like 09:00-14:00, separated by commas." });
});

test("coordinateText sends plain decimals with six places, or null", () => {
  assert.equal(coordinateText(""), null);
  assert.equal(coordinateText(" 7.38291234 "), "7.382912");
  assert.equal(coordinateText(5), "5.000000");
});

test("every category has a value and label, and values are unique", () => {
  assert.ok(CATEGORIES.length >= 2);
  assert.equal(new Set(CATEGORIES.map((c) => c.value)).size, CATEGORIES.length);
  for (const c of CATEGORIES) assert.match(c.value, /^[A-Z_]+$/);
});

// ---- paying first, pickup times ----
import { paymentWords, pickupText } from "../customer/js/order-view.js";

test("paymentWords says exactly where a payment stands", () => {
  assert.equal(paymentWords({ payment_status: "UNPAID" }), "Not paid yet");
  assert.match(paymentWords({ payment_status: "CLAIMED" }), /Waiting for the restaurant/);
  assert.equal(paymentWords({ payment_status: "PAID" }), "Paid");
});

test("pickupText names the day and never invents a time", () => {
  const now = new Date("2026-11-09T10:00:00");
  assert.equal(pickupText(null, now), "");
  assert.equal(pickupText("not a date", now), "");
  assert.match(pickupText("2026-11-09T13:15:00", now), /^Today /);
  assert.match(pickupText("2026-11-10T13:15:00", now), /^Tomorrow /);
  assert.doesNotMatch(pickupText("2026-11-12T13:15:00", now), /^(Today|Tomorrow)/);
});

// ---- reviews ----
import { RATING_WORDS, readRating, reviewDate, reviewSummary, starText } from "../shared/js/review-helpers.js";

test("starText shows only real whole ratings", () => {
  assert.equal(starText(4), "\u2605\u2605\u2605\u2605\u2606");
  assert.equal(starText(5), "\u2605".repeat(5));
  for (const bad of [0, 6, 2.5, "4", null, undefined, NaN]) assert.equal(starText(bad), "\u2606".repeat(5), String(bad));
});

test("readRating accepts the radio value of a whole 1-5 and nothing else", () => {
  assert.equal(readRating("3"), 3);
  for (const bad of ["", "0", "6", "2.5", "abc", null, undefined]) assert.equal(readRating(bad), null, String(bad));
});

test("every rating has a word and the summary never invents a score", () => {
  assert.deepEqual(Object.keys(RATING_WORDS), ["1", "2", "3", "4", "5"]);
  assert.equal(reviewSummary(null, 0), "No reviews yet");
  assert.equal(reviewSummary(4.5, 0), "No reviews yet");
  assert.equal(reviewSummary(4.33, 3), "4.3 out of 5 from 3 reviews");
  assert.equal(reviewSummary(5, 1), "5.0 out of 5 from 1 review");
  assert.equal(reviewDate("nonsense"), "");
  assert.match(reviewDate("2026-11-12T10:00:00Z"), /2026/);
});

// ---- late pickup policy ----
import { freeUntilText, lateFeeStatusText, lateFeeText } from "../shared/js/late-policy.js";

test("the late policy is explained in full, including that the clock waits for the restaurant", () => {
  const policy = { grace_minutes: 15, fee_amount: "100.00", interval_minutes: 15, max_fee: "300.00" };
  const text = lateFeeText(policy, (v) => `N${v}`);
  assert.match(text, /within 15 minutes of when it is ready/);
  assert.match(text, /late fee of N100\.00 applies for every 15 minutes/);
  assert.match(text, /up to N300\.00 in total/);
  assert.match(text, /only starts once the restaurant has marked your order ready/);
  assert.equal(lateFeeText(null, String), "");
});

test("freeUntilText never promises a time before the order is ready", () => {
  const policy = { free_until: null };
  assert.match(freeUntilText(policy, String), /starts when the restaurant marks your order ready/);
  assert.equal(freeUntilText({ free_until: "2026-11-09T14:25:00Z" }, () => "14:25"), "Collect by 14:25 to avoid a late fee.");
  assert.equal(freeUntilText(null, String), "");
});

test("late fee statuses read in words", () => {
  assert.equal(lateFeeStatusText("DUE"), "Due when you collect");
  assert.equal(lateFeeStatusText("WAIVED"), "Waived by the restaurant");
  assert.equal(lateFeeStatusText("NONE"), "");
});

// ---- customer accounts ----
import { STATUS_WORDS, fullName, orderSummary, safeNext as customerNext, trackHref } from "../customer/js/account-helpers.js";

test("the customer sign-in redirect only ever returns one of our own customer pages", () => {
  assert.equal(customerNext("checkout.html?r=green-bowl"), "checkout.html?r=green-bowl");
  assert.equal(customerNext("marketplace.html?q=rice&open=1"), "marketplace.html?q=rice&open=1");
  for (const bad of ["https://evil.example/", "//evil.example", "javascript:alert(1)", "order.html#abc", "../x.html", "account.html?next=https://x", "", null, undefined]) {
    assert.equal(customerNext(bad), "my-orders.html", String(bad));
  }
});

test("names and order lines read naturally", () => {
  assert.equal(fullName({ first_name: "Ada", last_name: "Obi" }), "Ada Obi");
  assert.equal(fullName({ first_name: "Ada", last_name: "" }), "Ada");
  assert.equal(fullName(null), "");
  assert.equal(orderSummary({ items_count: 1, fulfilment_type: "PICKUP" }), "1 item \u00b7 Pickup");
  assert.equal(orderSummary({ items_count: 3, fulfilment_type: "DINE_IN" }), "3 items \u00b7 Dine in");
  assert.equal(STATUS_WORDS.READY_FOR_PICKUP, "Ready");
});

test("an order link keeps the token after the # so servers and logs never see it", () => {
  const href = trackHref({ restaurant: { slug: "green bowl" }, track_token: "ab12" });
  assert.equal(href, "order.html?r=green%20bowl#ab12");
  assert.ok(!href.split("#")[0].includes("ab12"));
});
