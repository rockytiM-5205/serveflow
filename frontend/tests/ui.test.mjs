// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

test("el() skips null, undefined and false children instead of printing them", async () => {
  const made = [];
  globalThis.document = {
    createElement: () => {
      const node = { children: [], setAttribute() {}, addEventListener() {}, append(...items) { this.children.push(...items); } };
      made.push(node);
      return node;
    },
  };
  const { el } = await import("../shared/js/ui.js");
  const node = el("div", {}, "a", null, undefined, false, "b", 0);
  assert.deepEqual(node.children, ["a", "b", 0]);
});

test("planFacts() describes a plan in orders, never in API requests", async () => {
  globalThis.document ??= { createElement: () => ({ setAttribute() {}, addEventListener() {}, append() {} }) };
  const { planFacts } = await import("../shared/js/plan-facts.js");
  const facts = planFacts({ interval: "MONTHLY", included_orders: 300, included_requests: 67000, rate_limit_per_minute: 30, pack_orders: 100, pack_price: "2000.00", currency: "NGN" });
  assert.equal(facts[0], "300 orders each month");
  assert.ok(facts.some((f) => /Add 100 more orders/.test(f)));
  assert.ok(!facts.join(" ").match(/API|requests/i));
  assert.deepEqual(planFacts({ interval: "YEARLY", included_orders: 3000 }), ["3,000 orders each year", "Only finished orders count"]);
});
