import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { readFile } from "node:fs/promises";

const frontendRoot = path.resolve(import.meta.dirname, "..");

async function readRuntimeBundle() {
  const htmlPath = path.join(frontendRoot, "dist", "index.html");
  const html = await readFile(htmlPath, "utf8");
  const assetMatch = html.match(/assets\/(index-[^\"']+\.js)/);
  assert.ok(assetMatch, "dist/index.html must reference a built index asset");
  const bundlePath = path.join(frontendRoot, "dist", assetMatch[0]);
  return readFile(bundlePath, "utf8");
}

test("runtime dist bundle keeps cache-backed preview lookup for single-create proposal cards", async () => {
  const bundle = await readRuntimeBundle();

  assert.match(
    bundle,
    /Object\.defineProperty\([^)]*,"__attachedPreview",\{value:[^}]+enumerable:!1,configurable:!0\}\)/,
  );

  assert.match(
    bundle,
    /\.set\([^)]*\),Object\.defineProperty\([^)]*,"__attachedPreview",\{value:/,
  );

  assert.match(
    bundle,
    /__attachedPreview;if\([^)]*&&typeof [^)]*=="object"&&!Array\.isArray\([^)]*\)\)return [^;]+;const [^=]+=.+?\.get\([^)]*\)\?\?null:null/s,
  );
});