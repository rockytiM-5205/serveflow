// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

globalThis.document ??= { createElement: () => ({ setAttribute() {}, addEventListener() {}, append() {} }) };
const { shouldShow, SHOW_MS, NOT_NOW_DAYS, REMIND_HOURS } = await import("../shared/js/install-banner.js");

const NOW = Date.UTC(2026, 10, 16, 12, 0, 0);
const HOUR = 3600 * 1000;
const base = { now: NOW, state: {}, standalone: false, installable: true, ios: false };

test("a first-time visitor on a browser that can install sees the banner", () => {
  assert.equal(shouldShow(base), true);
  assert.equal(shouldShow({ ...base, installable: false, ios: true }), true); // iPhone: we show how to add it
});

test("it never shows inside the installed app, or where there is nothing to offer", () => {
  assert.equal(shouldShow({ ...base, standalone: true }), false);
  assert.equal(shouldShow({ ...base, installable: false, ios: false }), false);
});

test("after Not now it stays away for a week, then may come back", () => {
  const dismissedAt = NOW - 3 * 24 * HOUR;
  assert.equal(shouldShow({ ...base, state: { dismissedAt } }), false);
  assert.equal(shouldShow({ ...base, state: { dismissedAt: NOW - (NOT_NOW_DAYS * 24 + 1) * HOUR } }), true);
});

test("having been shown, it waits before appearing again so it never nags", () => {
  assert.equal(shouldShow({ ...base, state: { shownAt: NOW - 2 * HOUR } }), false);
  assert.equal(shouldShow({ ...base, state: { shownAt: NOW - (REMIND_HOURS + 1) * HOUR } }), true);
});

test("it stays up for a few seconds only", () => {
  assert.ok(SHOW_MS >= 5000 && SHOW_MS <= 7000);
});
