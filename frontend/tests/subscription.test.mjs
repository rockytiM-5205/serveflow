// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, api } from "../shared/js/api.js";
import { isSubscriptionEnded } from "../shared/js/subscription.js";

const reply = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const setup = (response) => {
  globalThis.document = { cookie: "" };
  globalThis.window = new EventTarget();
  globalThis.fetch = async () => response;
};

test("a 402 subscription_inactive reply is recognised and announced to the page", async () => {
  setup(reply(402, { error: { code: "subscription_inactive", message: "ended", details: {} } }));
  let announced = 0;
  window.addEventListener("serveflow:subscription-ended", () => announced++);
  await assert.rejects(api.post("/restaurants/x/menu/items/", {}), (err) => isSubscriptionEnded(err) && err.message === "ended");
  assert.equal(announced, 1);
});

test("other failures are not mistaken for an ended subscription", async () => {
  setup(reply(402, { error: { code: "something_else", message: "x" } }));
  let announced = 0;
  window.addEventListener("serveflow:subscription-ended", () => announced++);
  await assert.rejects(api.get("/x/"), (err) => err instanceof ApiError && !isSubscriptionEnded(err));
  setup(reply(403, { error: { code: "subscription_inactive", message: "x" } }));
  await assert.rejects(api.get("/x/"), (err) => !isSubscriptionEnded(err));
  assert.equal(announced, 0);
});

test("a FormData body is sent as multipart, with no JSON Content-Type", async () => {
  let seen;
  globalThis.document = { cookie: "csrftoken=tok" };
  globalThis.window = new EventTarget();
  globalThis.fetch = async (url, init) => { seen = init; return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } }); };
  const form = new FormData();
  form.append("file", new Blob(["x"], { type: "image/png" }), "a.png");
  await api.upload("/restaurants/x/images/logo/", form);
  assert.ok(seen.body instanceof FormData);
  assert.equal(seen.headers["Content-Type"], undefined);
  assert.equal(seen.headers["X-CSRFToken"], "tok");
  assert.equal(seen.method, "POST");
});
