// Run from frontend/ with: node --test
// Guards the design system: brand tokens, the font stack, and that every icon the code asks for exists in the sprite.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";

const root = new URL("..", import.meta.url).pathname;
const read = (p) => readFileSync(join(root, p), "utf8");
const walk = (dir, out = []) => {
  for (const name of readdirSync(dir)) {
    if (["node_modules", "tests", "visual_out"].includes(name) || name.startsWith(".")) continue;
    const full = join(dir, name);
    statSync(full).isDirectory() ? walk(full, out) : out.push(full);
  }
  return out;
};

test("the premium theme uses the brand colours from the brief", () => {
  const tokens = read("shared/css/themes/premium/tokens.css");
  for (const [name, hex] of [["--brand-900", "#064e3b"], ["--brand-950", "#022c22"], ["--brand-300", "#86efac"], ["--bg", "#f8faf9"], ["--surface", "#ffffff"], ["--ink", "#1f2937"]]) {
    assert.match(tokens, new RegExp(`${name}:\\s*${hex}`, "i"), `${name} should be ${hex}`);
  }
});

test("the premium type system is Geist first, with Plus Jakarta Sans for customer headings and a safe fallback", () => {
  const tokens = read("shared/css/themes/premium/tokens.css");
  assert.match(tokens, /--font:\s*"Geist",[^;]*system-ui/);
  assert.match(tokens, /--font-display:\s*"Plus Jakarta Sans"/);
  assert.match(read("shared/css/themes/premium/customer.css"), /var\(--font-display\)/);
  assert.match(read("tools/fetch_fonts.py".replace("tools/", "../tools/")), /Geist/);
});

test("every page that loads the tokens also loads the fonts first", () => {
  for (const file of walk(root).filter((f) => f.endsWith(".html"))) {
    const html = readFileSync(file, "utf8");
    if (!html.includes("tokens.css")) continue;
    assert.ok(html.indexOf("fonts.css") !== -1 && html.indexOf("fonts.css") < html.indexOf("tokens.css"), `${relative(root, file)} should load fonts.css before tokens.css`);
  }
});

test("every icon used by the pages and scripts exists in the Lucide sprite", () => {
  const sprite = new Set([...read("shared/assets/icons.svg").matchAll(/id="i-([a-z0-9-]+)"/g)].map((m) => m[1]));
  assert.ok(sprite.size > 40);
  const missing = [];
  for (const file of walk(root).filter((f) => /\.(js|html)$/.test(f))) {
    const source = readFileSync(file, "utf8");
    const used = [...source.matchAll(/icon\(\s*"([a-z0-9-]+)"/g), ...source.matchAll(/#i-([a-z0-9-]+)/g), ...source.matchAll(/\bicon:\s*"([a-z0-9-]+)"/g)].map((m) => m[1]);
    for (const name of used) if (!sprite.has(name)) missing.push(`${relative(root, file)}: ${name}`);
  }
  assert.deepEqual(missing, [], "icons used but not in shared/assets/icons.svg");
});

test("the icon sprite is stroke-based Lucide geometry on a 24px grid", () => {
  const sprite = read("shared/assets/icons.svg");
  assert.equal([...sprite.matchAll(/<symbol /g)].length, [...sprite.matchAll(/viewBox="0 0 24 24"/g)].length);
  assert.ok(!/fill="#|stroke="#/.test(sprite), "colour comes from the .icon class (currentColor), never from the sprite");
});
