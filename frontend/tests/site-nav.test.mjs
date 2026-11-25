// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

globalThis.document ??= { createElement: () => ({ setAttribute() {}, addEventListener() {}, append() {} }) };
const { navItems, pageName } = await import("../customer/js/site-nav.js");
const ids = (items) => items.map((i) => i.id);

test("pageName() names the page from its address", () => {
  assert.equal(pageName("/customer/menu.html"), "menu");
  assert.equal(pageName("/customer/my-orders.html"), "my-orders");
  assert.equal(pageName("/customer/"), "index");
  assert.equal(pageName(undefined), "index");
});

test("on a restaurant page the menu has this restaurant first, then all restaurants and sign in", () => {
  const items = navItems({ page: "menu", slug: "green-bowl" });
  assert.deepEqual(ids(items), ["menu", "about", "restaurants", "signin"]);
  assert.equal(items[0].href, "menu.html?r=green-bowl");
  assert.equal(items.find((i) => i.current).id, "menu");
});

test("Track order only appears when there is an order to track, and links to it", () => {
  assert.ok(!ids(navItems({ page: "menu", slug: "green-bowl" })).includes("track"));
  const track = navItems({ page: "menu", slug: "green-bowl", trackToken: "abc123" }).find((i) => i.id === "track");
  assert.equal(track.href, "order.html?r=green-bowl#abc123");
});

test("without a restaurant (marketplace, account pages) only the general links show", () => {
  assert.deepEqual(ids(navItems({ page: "marketplace" })), ["restaurants", "signin"]);
  assert.equal(navItems({ page: "marketplace" }).find((i) => i.current).id, "restaurants");
});

test("a signed-in customer sees My orders instead of Sign in", () => {
  const items = navItems({ page: "menu", slug: "green-bowl", customer: { first_name: "Ada" } });
  assert.ok(ids(items).includes("orders") && !ids(items).includes("signin"));
  assert.equal(items.find((i) => i.id === "orders").href, "my-orders.html");
});

test("Sign in remembers where the customer was, but never an address that carries an order link", () => {
  assert.equal(navItems({ page: "menu", slug: "x-y-z", here: "?next=menu.html%3Fr%3Dx-y-z" }).at(-1).href, "account.html?next=menu.html%3Fr%3Dx-y-z");
  assert.equal(navItems({ page: "order", slug: "x-y-z", here: "" }).at(-1).href, "account.html");
});

test("each page marks its own link as the current one", () => {
  for (const [page, id] of [["index", "about"], ["checkout", "menu"], ["order", "track"], ["my-orders", "orders"], ["account", "signin"]]) {
    const items = navItems({ page, slug: "green-bowl", trackToken: "t", customer: page === "my-orders" ? { first_name: "A" } : null });
    assert.equal(items.find((i) => i.current)?.id, id, page);
  }
});
