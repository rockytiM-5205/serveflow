// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

import { ApiError } from "../shared/js/api.js";
import { NOT_AVAILABLE, buildQuery, isNotAvailable, platform } from "../owner-control-centre/js/platform-api.js";
import { fmtMoney, fmtPercent, label } from "../owner-control-centre/js/components.js";

const json = (body, init = {}) => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" }, ...init });
function stub(handler) {
  const calls = [];
  globalThis.document = { cookie: "" };
  globalThis.window = new EventTarget();
  globalThis.fetch = async (url, init) => { calls.push({ url, init }); return handler(url, init); };
  return calls;
}

test("buildQuery skips empty values and encodes the rest", () => {
  assert.equal(buildQuery({ search: " a b ", status: "", plan: undefined }), "?search=a+b");
  assert.equal(buildQuery({}), "");
});

test("a missing owner endpoint is reported as not_available, never as data", async () => {
  for (const status of [404, 405, 501]) {
    stub(() => json({ error: { code: "not_found", message: "x" } }, { status }));
    await assert.rejects(platform.overview("30d"), (err) => err instanceof ApiError && err.code === NOT_AVAILABLE && isNotAvailable(err));
  }
});

test("401 asks the app to sign in again; 403 stays a normal error", async () => {
  stub(() => json({ error: { code: "not_authenticated", message: "x" } }, { status: 401 }));
  let fired = 0;
  globalThis.window.addEventListener("owner:unauthenticated", () => fired++);
  await assert.rejects(platform.me(), (err) => err.status === 401);
  assert.equal(fired, 1);
  stub(() => json({ error: { code: "permission_denied", message: "no" } }, { status: 403 }));
  await assert.rejects(platform.list("customers", ""), (err) => err.status === 403 && !isNotAvailable(err));
});

test("writes carry the CSRF header and use the proposed paths", async () => {
  const calls = stub(() => json({ ok: true }));
  globalThis.document.cookie = "csrftoken=abc";
  await platform.action("credentials", "k 1", "revoke");
  assert.equal(calls[0].url, "/api/v1/platform/credentials/k%201/revoke/");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers["X-CSRFToken"], "abc");
});

test("formatters give a dash, not a made-up number, for missing values", () => {
  assert.equal(fmtPercent(undefined), "—");
  assert.equal(fmtMoney("abc", "NGN"), "—");
  assert.match(fmtPercent(0.0123), /^1\.23%$/);
  assert.equal(label("PAST_DUE"), "Past due");
});

import { timeAgo } from "../owner-control-centre/js/components.js";

test("timeAgo reads naturally and survives bad input", () => {
  const now = Date.parse("2026-11-03T12:00:00Z");
  assert.equal(timeAgo("2026-11-03T11:59:40Z", now), "just now");
  assert.equal(timeAgo("2026-11-03T11:30:00Z", now), "30 min ago");
  assert.equal(timeAgo("2026-11-03T09:00:00Z", now), "3 h ago");
  assert.equal(timeAgo("2026-11-01T12:00:00Z", now), "2 d ago");
  assert.equal(timeAgo(null, now), "");
  assert.equal(timeAgo("not a date", now), "");
});
