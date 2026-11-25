// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

import { estimateLimits } from "../owner-control-centre/js/estimator.js";

test("matches the worked examples in docs/api-guide.md", () => {
  assert.equal(estimateLimits({ ordersPerDay: 30, cacheSeconds: 0 }).perMonth, 9900);      // small, uncached
  assert.equal(estimateLimits({ ordersPerDay: 150, cacheSeconds: 0 }).perMonth, 49500);    // medium, uncached
  assert.equal(estimateLimits({ ordersPerDay: 500, cacheSeconds: 0 }).perMonth, 165000);   // large, uncached
  assert.equal(estimateLimits({ ordersPerDay: 30, cacheSeconds: 60 }).perMonth, 22500);    // small, menu cached 60 s
});

test("suggests allowances with headroom, in round numbers", () => {
  const small = estimateLimits({ ordersPerDay: 30, cacheSeconds: 0 });
  assert.equal(small.suggestedMonthly, 25000);
  assert.ok(small.suggestedPerMinute >= 10);
  assert.equal(estimateLimits({ ordersPerDay: 500, cacheSeconds: 0 }).suggestedMonthly, 413000);
});

test("bad input falls back to safe defaults instead of NaN", () => {
  const result = estimateLimits({ ordersPerDay: "abc", openHours: -4, cacheSeconds: NaN });
  assert.ok(Object.values(result).every(Number.isFinite));
});
