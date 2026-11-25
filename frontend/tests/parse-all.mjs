/* Parses every frontend module as an ES module (without running it). `node --check` is not reliable for these files. */
import vm from "node:vm";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
const files = [];
(function walk(d) { for (const f of readdirSync(d)) { if (f === "node_modules") continue; const p = join(d, f); statSync(p).isDirectory() ? walk(p) : (p.endsWith(".js") || p.endsWith(".mjs")) && files.push(p); } })(process.argv[2] ?? ".");
let bad = 0;
for (const f of files) {
  try { new vm.SourceTextModule(readFileSync(f, "utf8"), { identifier: f }); } catch (e) { bad += 1; console.log("SYNTAX", f, e.message); }
}
console.log(`${files.length} modules parsed, ${bad} with syntax errors`);
