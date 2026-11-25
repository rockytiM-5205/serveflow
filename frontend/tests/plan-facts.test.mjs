// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

globalThis.document ??= { createElement: () => ({ setAttribute() {}, addEventListener() {}, append() {} }) };
const { planFacts } = await import("../shared/js/plan-facts.js");

test("a plan is described in orders, never in API requests", () => {
  const facts = planFacts({ interval: "MONTHLY", included_orders: 300, included_requests: 67000, rate_limit_per_minute: 30, currency: "NGN" });
  assert.deepEqual(facts, ["300 orders each month", "Only finished orders count"]);
  assert.ok(!facts.join(" ").match(/API|requests/i));
});

test("an extra order pack is offered when the plan has one", () => {
  const facts = planFacts({ interval: "YEARLY", included_orders: 4000, pack_orders: 500, pack_price: "5000.00", currency: "NGN" });
  assert.equal(facts[0], "4,000 orders each year");
  assert.match(facts[2], /^Busy month\? Add 500 more orders for .*5,000/);
});

test("a plan without an order allowance shows nothing technical", () => {
  assert.deepEqual(planFacts({ interval: "MONTHLY", included_requests: 1000, rate_limit_per_minute: 5 }), []);
});
