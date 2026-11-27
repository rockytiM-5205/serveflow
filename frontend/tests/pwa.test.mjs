// Run from frontend/ with: node --test
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { restaurantManifestHref, useRestaurantManifest, useHomeScreenIcon, canInstall, registerServiceWorker } from "../shared/js/pwa.js";
import { keyToBytes } from "../restaurant-dashboard/js/push-client.js";

const fakeDoc = (selectorsToNodes) => ({ querySelector: (s) => selectorsToNodes[s] ?? null });
const node = () => ({ attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } });

test("a restaurant's manifest lives on its own address, with the slug made safe", () => {
  assert.equal(restaurantManifestHref("green-bowl"), "/api/v1/restaurants/green-bowl/manifest.webmanifest");
  assert.equal(restaurantManifestHref("a/b"), "/api/v1/restaurants/a%2Fb/manifest.webmanifest");
});

test("a restaurant page swaps its manifest link for that restaurant's own", () => {
  const link = node();
  useRestaurantManifest("green-bowl", { document: fakeDoc({ 'link[rel="manifest"]': link }) });
  assert.equal(link.attrs.href, "/api/v1/restaurants/green-bowl/manifest.webmanifest");
  useRestaurantManifest(null, { document: fakeDoc({ 'link[rel="manifest"]': link }) }); // no slug: left alone
  assert.equal(link.attrs.href, "/api/v1/restaurants/green-bowl/manifest.webmanifest");
});

test("a page without a manifest link doesn't break", () => {
  assert.doesNotThrow(() => useRestaurantManifest("green-bowl", { document: fakeDoc({}) }));
  assert.doesNotThrow(() => useHomeScreenIcon("/media/x.webp", { document: fakeDoc({}) }));
});

test("the restaurant's logo becomes the home-screen icon", () => {
  const link = node();
  useHomeScreenIcon("/media/restaurants/1/logo/a.webp", { document: fakeDoc({ 'link[rel="apple-touch-icon"]': link }) });
  assert.equal(link.attrs.href, "/media/restaurants/1/logo/a.webp");
});

test("without a browser that can install, nothing is offered and registering quietly does nothing", async () => {
  assert.equal(canInstall(), false);
  assert.equal(await registerServiceWorker("sw.js", "./"), null);
});

test("the server's public key becomes the bytes the browser wants", () => {
  assert.deepEqual([...keyToBytes("AAEC")], [0, 1, 2]);            // plain base64url
  assert.deepEqual([...keyToBytes("-_8")], [251, 255]);            // url-safe characters and missing padding
  assert.equal(keyToBytes("A".repeat(87)).length, 65);             // the size of a real VAPID public key
});

// The service worker's rules are the safety net for orders and payments: check them in the source, since a worker can't be run here.
const core = readFileSync(new URL("../shared/js/sw-core.js", import.meta.url), "utf8");

test("the service worker never keeps live data and only handles page and file requests", () => {
  assert.match(core, /LIVE = \/\^\\\/\(api\|admin\|media\|static\)\\\//);
  assert.match(core, /request\.method !== "GET"\) return/);
  assert.match(core, /url\.origin !== self\.location\.origin \|\| LIVE\.test\(url\.pathname\)\) return/);
});

test("the service worker asks the network first and shows the offline page only when there is no connection", () => {
  assert.ok(core.indexOf("await fetch(request)") < core.indexOf("caches.match(request)"));
  assert.match(core, /\/shared\/offline\.html/);
});

test("alerts only open pages inside the dashboard", () => {
  assert.match(core, /startsWith\("\/restaurant-dashboard\/"\)/);
});

test("each app has its own manifest, scope and service worker", () => {
  for (const [dir, scope] of [["restaurant-dashboard", "/restaurant-dashboard/"], ["customer", "/customer/"]]) {
    const manifest = JSON.parse(readFileSync(new URL(`../${dir}/manifest.webmanifest`, import.meta.url), "utf8"));
    assert.equal(manifest.scope, scope);
    assert.ok(manifest.start_url.startsWith(scope), `${dir} start_url is inside its scope`);
    assert.equal(manifest.display, "standalone");
    assert.ok(manifest.icons.some((i) => i.sizes === "192x192") && manifest.icons.some((i) => i.sizes === "512x512"));
    assert.match(readFileSync(new URL(`../${dir}/sw.js`, import.meta.url), "utf8"), /serveflowServiceWorker\(/);
  }
});

import { sameKey } from "../restaurant-dashboard/js/push-client.js";

test("a subscription made with an older server key is recognised so it can be replaced", () => {
  const key = "BAUG"; // any valid base64url text
  const current = keyToBytes(key);
  assert.equal(sameKey({ options: { applicationServerKey: current.buffer } }, key), true);
  assert.equal(sameKey({ options: { applicationServerKey: new Uint8Array([1, 2, 3]).buffer } }, key), false);
  assert.equal(sameKey({ options: {} }, key), true); // the browser doesn't say: keep what works
});
