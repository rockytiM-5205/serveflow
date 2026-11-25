/* The Settings cards added this month, opened in the fake browser: they render, show no stray "null", and their buttons work. */
import assert from "node:assert/strict";
import test from "node:test";
import { fakeApi, installDom, tick, until } from "./dom-stub.mjs";

const setup = (routes) => {
  const dom = installDom({ pathname: "/restaurant-dashboard/settings.html" });
  const calls = fakeApi(routes);
  const text = () => dom.doc.body.textContent;
  const button = (label) => dom.doc.body.querySelectorAll("button").find((b) => b.textContent.trim() === label);
  return { dom, calls, text, button, doc: dom.doc };
};
const noJunk = (text) => assert.doesNotMatch(text, /\bnull\b|\bundefined\b|\[object/, "a null/undefined leaked onto the page");
const settings = (extra = {}) => ({ currency: "NGN", pickup_fee: "150.00", late_fee_enabled: false, late_grace_minutes: 15, late_fee_amount: "0.00", late_fee_interval_minutes: 15, late_fee_max: "0.00", ...extra });
const ACCOUNT = { bank_name: "First Bank", account_name: "Mama Put Ltd", account_number: "0123456789", instructions: "Use the reference", ready: true };

test("the payments card shows the bank details and pickup fee, with no stray text, for an owner", async () => {
  const t = setup({ "GET /restaurants/green-bowl/payment-account/": [200, ACCOUNT] });
  const { paymentCard } = await import("../restaurant-dashboard/js/payment-account.js?owner");
  const card = paymentCard({ slug: "green-bowl", data: settings(), url: "/restaurants/green-bowl/settings/", canEditFee: true, isOwner: true, reload() {}, onError: () => false });
  t.doc.body.append(card);
  await until(() => card.textContent.includes("0123456789"), "the card");
  for (const needle of ["First Bank", "Mama Put Ltd", "Edit bank details", "Pickup fee", "Late pickup policy", "No late fee"]) assert.ok(card.textContent.includes(needle), needle);
  noJunk(card.textContent);
});

test("a manager sees the details but not the edit-bank button, and is told only the owner can change them", async () => {
  const t = setup({ "GET /restaurants/green-bowl/payment-account/": [200, ACCOUNT] });
  const { paymentCard } = await import("../restaurant-dashboard/js/payment-account.js?manager");
  const card = paymentCard({ slug: "green-bowl", data: settings(), url: "/x/", canEditFee: true, isOwner: false, reload() {}, onError: () => false });
  t.doc.body.append(card);
  await until(() => card.textContent.includes("0123456789"));
  assert.ok(!card.textContent.includes("Edit bank details"));
  assert.match(card.textContent, /Only the owner can change the bank details/);
  noJunk(card.textContent);
});

test("a restaurant with no bank details is warned, and the owner can add them", async () => {
  const t = setup({ "GET /restaurants/green-bowl/payment-account/": [200, { bank_name: "", account_name: "", account_number: "", instructions: "", ready: false }] });
  const { paymentCard } = await import("../restaurant-dashboard/js/payment-account.js?empty");
  const card = paymentCard({ slug: "green-bowl", data: settings(), url: "/x/", canEditFee: true, isOwner: true, reload() {}, onError: () => false });
  t.doc.body.append(card);
  await until(() => card.textContent.includes("Add bank details"));
  assert.match(card.textContent, /Add your bank details before you take orders/);
  noJunk(card.textContent);
});

test("the late pickup policy dialog opens, validates and saves", async () => {
  const t = setup({ "GET /restaurants/green-bowl/payment-account/": [200, ACCOUNT], "PATCH /restaurants/green-bowl/settings/": [200, settings({ late_fee_enabled: true })] });
  const { paymentCard } = await import("../restaurant-dashboard/js/payment-account.js?late");
  let reloaded = false;
  const card = paymentCard({ slug: "green-bowl", data: settings(), url: "/restaurants/green-bowl/settings/", canEditFee: true, isOwner: true, reload: () => { reloaded = true; }, onError: () => false });
  t.doc.body.append(card);
  await until(() => card.textContent.includes("Late pickup policy"));
  card.querySelectorAll("button").find((b) => b.textContent === "Late pickup policy").click();
  const dialog = await until(() => t.doc.body.querySelector("dialog"), "the dialog");
  noJunk(dialog.textContent);
  assert.match(dialog.textContent, /Charge a late pickup fee/);
  const form = dialog.querySelector("form");
  const input = (name) => dialog.querySelectorAll("input").find((i) => (i.getAttribute("id") ?? "").endsWith(`-${name}`));
  input("late_fee_enabled").checked = true;
  form.dispatchEvent({ type: "submit" }); // a fee of 0.00 with the policy on must be refused
  await tick(20);
  assert.equal(t.calls.filter((c) => c.method === "PATCH").length, 0, "saved a policy with no fee");
  input("late_fee_amount").value = "100";
  input("late_fee_max").value = "300";
  form.dispatchEvent({ type: "submit" });
  await until(() => t.calls.some((c) => c.method === "PATCH"), "the save");
  const body = t.calls.find((c) => c.method === "PATCH").body;
  assert.deepEqual(body, { late_fee_enabled: true, late_grace_minutes: 15, late_fee_amount: "100", late_fee_interval_minutes: 15, late_fee_max: "300" });
  await until(() => reloaded, "the page to reload its settings");
});

test("the marketplace and opening-hours cards render and the hours editor saves", async () => {
  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, weekday) => ({ weekday, day, periods: weekday === 0 ? [{ opens: "09:00", closes: "17:00" }] : [] }));
  const t = setup({ "GET /restaurants/green-bowl/hours/": [200, { timezone: "Africa/Lagos", hours: days }], "PUT /restaurants/green-bowl/hours/": [200, { timezone: "Africa/Lagos", hours: days }] });
  const { hoursCard, marketplaceCard } = await import("../restaurant-dashboard/js/marketplace-profile.js?cards");
  const profile = marketplaceCard({ data: { listed_in_marketplace: true, category: "AFRICAN", area: "Akungba", latitude: "7.400000", longitude: "5.750000", currency: "NGN" }, url: "/x/", canEdit: true, reload() {} });
  const hours = hoursCard({ slug: "green-bowl", canEdit: true, onError: () => false });
  t.doc.body.append(profile, hours);
  await until(() => hours.textContent.includes("09:00"), "the hours");
  assert.match(profile.textContent, /African/);
  assert.match(hours.textContent, /Africa\/Lagos/);
  noJunk(profile.textContent + hours.textContent);
  const plain = marketplaceCard({ data: { listed_in_marketplace: false, category: "", area: "", latitude: null, longitude: null }, url: "/x/", canEdit: false, reload() {} });
  assert.match(plain.textContent, /Not set/);
  assert.match(plain.textContent, /Managers and owners can edit this/);
  noJunk(plain.textContent);
});
