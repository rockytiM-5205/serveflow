import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

test("every frontend module parses as a real ES module", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const script = fileURLToPath(new URL("./parse-all.mjs", import.meta.url));
  const run = spawnSync(process.execPath, ["--experimental-vm-modules", "--no-warnings", script, root], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stderr);
  assert.match(run.stdout, /\d+ modules parsed, 0 with syntax errors/, run.stdout);
});
