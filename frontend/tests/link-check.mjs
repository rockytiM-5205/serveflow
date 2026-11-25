/* Does every page script LOAD in a browser? It links each page's module graph the way the browser does: every file it imports must
 * exist, and every name it imports must be exported by that file. A mixed or half-copied project fails here with the exact file.
 * Run:  node --experimental-vm-modules --no-warnings frontend/tests/link-check.mjs [frontend-folder] */
import vm from "node:vm";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";

const root = resolve(process.argv[2] ?? ".");
const cache = new Map();
const problems = [];

function load(file) {
  if (cache.has(file)) return cache.get(file);
  const mod = new vm.SourceTextModule(readFileSync(file, "utf8"), { identifier: file, initializeImportMeta() {} });
  cache.set(file, mod);
  return mod;
}

async function linkPage(entry) {
  const missing = [];
  try {
    const top = load(entry);
    await top.link((specifier, referencing) => {
      if (!specifier.startsWith(".")) throw new Error(`unexpected non-relative import "${specifier}"`);
      const target = resolve(dirname(referencing.identifier), specifier);
      if (!existsSync(target)) { missing.push(`${relative(root, referencing.identifier)} imports ${specifier}, which does not exist`); throw new Error(`missing file ${relative(root, target)}`); }
      return load(target);
    });
  } catch (error) {
    problems.push({ page: relative(root, entry), error: missing[0] ?? error.message });
  }
}

const pages = [];
(function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "tests") continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) { walk(path); continue; }
    if (!name.endsWith(".html")) continue;
    for (const m of readFileSync(path, "utf8").matchAll(/<script[^>]*type="module"[^>]*src="([^"]+)"/g)) {
      const script = resolve(dir, m[1]);
      if (existsSync(script)) pages.push(script);
      else problems.push({ page: relative(root, path), error: `loads ${m[1]}, which does not exist` });
    }
  }
})(root);

for (const page of new Set(pages)) { cache.clear(); await linkPage(page); }
if (problems.length) {
  for (const p of problems) console.log(`BROKEN  ${p.page}: ${p.error}`);
  console.log(`${problems.length} page script(s) would not load.`);
  process.exit(1);
}
console.log(`${new Set(pages).size} page scripts all load: every import exists and every imported name is exported.`);
