// Run from frontend/ with: node --test
// The header menu is built from several optional parts (install, track order, sign in). A part that is absent must leave nothing behind:
// a stray null used to be printed as the word "null" next to Sign in.
import assert from "node:assert/strict";
import test from "node:test";
import { fakeApi, installDom, tick } from "./dom-stub.mjs";

test("the header menu never prints the word null, whatever is missing", async () => {
  const { doc, body } = installDom({ search: "?r=green-bowl", pathname: "/customer/menu.html" });
  fakeApi({});
  const bar = doc.createElement("div");
  bar.setAttribute("class", "container topbar__inner");
  body.append(bar);
  const { mountSiteNav } = await import("../customer/js/site-nav.js");
  mountSiteNav({ slug: "green-bowl" });
  await tick(20);
  const text = body.textContent;
  assert.ok(!/null|undefined/.test(text), `the menu printed a stray value: ${text}`);
  assert.match(text, /All restaurants/);
  assert.match(text, /Sign in/);
});
