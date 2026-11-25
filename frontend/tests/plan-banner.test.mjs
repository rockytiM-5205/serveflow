// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

import { timeLeft } from "../restaurant-dashboard/js/plan-banner.js";

test("timeLeft says how long a trial has left, and nothing once it's over", () => {
  assert.equal(timeLeft(0), null);
  assert.equal(timeLeft(-5000), null);
  assert.equal(timeLeft(30 * 1000), "1 min");
  assert.equal(timeLeft(95 * 60 * 1000), "1 h 35 min");
  assert.equal(timeLeft(26 * 3600 * 1000), "1 day 2 h");
  assert.equal(timeLeft(48 * 3600 * 1000), "2 days");
});
