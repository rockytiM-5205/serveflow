// Run from frontend/ with: node --test
// ServeFlow ships two designs, "classic" (the earlier one, the launch default) and "premium". tools/set_theme.py copies the chosen one over the
// live stylesheets. These tests keep the live files and the chosen theme from drifting apart, and keep both designs able to style the same markup.
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname;
const read = (p) => readFileSync(join(root, p), "utf8");
const THEMES = "shared/css/themes";
const FILES = {
  "tokens.css": "shared/css/tokens.css", "base.css": "shared/css/base.css", "layout.css": "shared/css/layout.css", "components.css": "shared/css/components.css",
  "plans.css": "shared/css/plans.css", "customer.css": "customer/css/customer.css", "marketplace.css": "customer/css/marketplace.css",
  "dashboard.css": "restaurant-dashboard/css/dashboard.css", "owner.css": "owner-control-centre/css/owner.css",
};
const themes = readdirSync(join(root, THEMES), { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name);

test("there are two designs, and one of them is active", () => {
  assert.deepEqual(themes.sort(), ["classic", "premium"]);
  assert.ok(themes.includes(read(`${THEMES}/ACTIVE`).trim()));
});

test("the live stylesheets are exactly the active theme (run tools/set_theme.py after editing a theme)", () => {
  const active = read(`${THEMES}/ACTIVE`).trim();
  assert.ok(themes.includes(active));
  for (const [name, live] of Object.entries(FILES)) {
    assert.equal(read(live), read(`${THEMES}/${active}/${name}`), `${live} differs from ${THEMES}/${active}/${name}`);
  }
});

test("both designs have the same set of files", () => {
  for (const theme of themes) assert.deepEqual(readdirSync(join(root, THEMES, theme)).sort(), Object.keys(FILES).sort());
});

test("both designs can style the shared markup (workspace navigation, marketplace search)", () => {
  const needs = { "layout.css": [".nav__more", ".nav__item--secondary", ".nav__workspace"], "dashboard.css": [".sheet-link", ".avatar", ".search-row"], "marketplace.css": [".market-search", ".input-icon", ".market-more"] };
  for (const theme of themes) {
    for (const [file, selectors] of Object.entries(needs)) {
      const css = read(`${THEMES}/${theme}/${file}`);
      for (const selector of selectors) assert.ok(css.includes(selector), `${theme}/${file} should style ${selector}`);
    }
  }
});

for (const file of ["customer/css/order-scene.css", "customer/css/reviews.css"]) test(`${file} uses only tokens both designs define`, () => {
  const scene = read(file);
  const defined = (theme) => new Set([...read(`${THEMES}/${theme}/tokens.css`).matchAll(/(--[a-z0-9-]+):/g)].map((m) => m[1]));
  const script = read(file.replace("css/", "js/").replace("reviews.css", "review-carousel.js").replace("order-scene.css", "order-scene.js")); // the drawing sets some per-element values itself (--x, --delay ...)
  const local = new Set([...script.matchAll(/(--[a-z0-9-]+):/g)].map((m) => m[1]));
  const used = [...scene.matchAll(/var\((--[a-z0-9-]+)\)/g)].map((m) => m[1]).filter((v) => !v.startsWith("--os-") && !local.has(v)); // a var() with a fallback is safe in either design
  for (const theme of themes) for (const name of used) assert.ok(defined(theme).has(name) || scene.includes(`${name}:`), `${name} is not defined by the ${theme} theme`);
});
