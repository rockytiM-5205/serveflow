import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

test("every page script links: each import exists and every imported name is exported", () => {
  const root = fileURLToPath(new URL("..", import.meta.url));
  const script = fileURLToPath(new URL("./link-check.mjs", import.meta.url));
  const run = spawnSync(process.execPath, ["--experimental-vm-modules", "--no-warnings", script, root], { encoding: "utf8" });
  assert.equal(run.status, 0, run.stdout + run.stderr);
});
