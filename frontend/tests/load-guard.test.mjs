import assert from "node:assert/strict";
import test from "node:test";
import { installDom, tick } from "./dom-stub.mjs";

let n = 0;
async function pageWith(skeleton) {
  n += 1;
  const dom = installDom({ pathname: "/customer/order.html" });
  const { doc, body } = dom;
  const content = doc.createElement("div");
  content.setAttribute("id", "content");
  if (skeleton) { const s = doc.createElement("div"); s.setAttribute("class", "skeleton"); content.append(s); } else content.append("The real page");
  body.append(content);
  await import(`../shared/js/load-guard.js?n=${n}`);
  return { content };
}

test("a page that cannot start explains itself instead of staying blank", async () => {
  const { content } = await pageWith(true);
  const event = new Event("error");
  event.message = "The requested module does not provide an export named 'x'";
  globalThis.dispatchEvent(event);
  await tick(5);
  assert.match(content.textContent, /This page couldn't start/);
  assert.match(content.textContent, /does not provide an export named 'x'/);
  assert.ok(content.querySelectorAll("button").some((b) => b.textContent === "Refresh"));
});

test("a page that is working is left alone", async () => {
  const { content } = await pageWith(false);
  const event = new Event("error");
  event.message = "some unrelated warning";
  globalThis.dispatchEvent(event);
  await tick(5);
  assert.equal(content.textContent, "The real page");
});
