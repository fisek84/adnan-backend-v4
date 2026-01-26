import { access, readFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

const isWin = process.platform === "win32";
const npmCmd = "npm";

async function exists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

function assert(condition, message) {
  if (!condition) {
    const err = new Error(message);
    err.name = "PwaSmokeTestError";
    throw err;
  }
}

async function fetchOk(url) {
  const res = await fetch(url, { redirect: "follow" });
  assert(res.status === 200, `${url} expected 200, got ${res.status}`);
  return res;
}

async function waitForHttp(url, timeoutMs = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {
      // ignore
    }
    await delay(250);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function main() {
  // 1) Source-level checks (fast)
  assert(await exists("public/manifest.webmanifest"), "Missing public/manifest.webmanifest");
  assert(await exists("public/offline.html"), "Missing public/offline.html");
  assert(await exists("public/service-worker.js"), "Missing public/service-worker.js");

  const indexHtml = await readFile("index.html", "utf8");
  assert(indexHtml.includes('rel="manifest"'), "index.html missing manifest link");
  assert(indexHtml.includes('name="apple-mobile-web-app-capable"'), "index.html missing iOS meta");
  assert(indexHtml.includes('rel="apple-touch-icon"'), "index.html missing apple-touch-icon link");

  // 2) Build (ensure preview serves current output)
  if (process.env.PWA_SKIP_BUILD !== "true") {
    process.stdout.write("[pwa-smoke] running build...\\n");
    const build = spawn(npmCmd, ["run", "build"], { stdio: "inherit", shell: isWin });
    const code = await new Promise((resolve) => build.on("close", resolve));
    assert(code === 0, `Build failed with exit code ${code}`);
  }

  // 3) Preview server + HTTP checks (manifest/offline/SW should be 200)
  const port = Number(process.env.PWA_TEST_PORT || 4173);
  const baseUrl = `http://localhost:${port}`;

  process.stdout.write(`[pwa-smoke] starting vite preview on ${baseUrl}...\n`);
  const child = spawn(npmCmd, ["run", "preview", "--", "--port", String(port), "--strictPort"], {
    stdio: "pipe",
    shell: isWin,
  });

  let logs = "";
  child.stdout.on("data", (d) => (logs += d.toString()));
  child.stderr.on("data", (d) => (logs += d.toString()));

  try {
    await waitForHttp(`${baseUrl}/`, 20000);

    await fetchOk(`${baseUrl}/manifest.webmanifest`);
    await fetchOk(`${baseUrl}/offline.html`);
    await fetchOk(`${baseUrl}/service-worker.js`);

    const htmlRes = await fetchOk(`${baseUrl}/`);
    const html = await htmlRes.text();
    assert(html.includes('rel="manifest"'), "/ HTML missing manifest link");
    assert(html.includes('name="apple-mobile-web-app-capable"'), "/ HTML missing iOS meta");

    process.stdout.write("[pwa-smoke] OK\n");
  } finally {
    // best-effort shutdown
    try {
      child.kill();
    } catch {
      // ignore
    }

    // On Windows, ensure child is terminated.
    if (isWin && child.pid) {
      spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore" });
    }

    if (logs) {
      // Only print logs on failure? Keep short.
    }
  }
}

main().catch((err) => {
  console.error("[pwa-smoke] FAILED:", err?.message || err);
  process.exit(1);
});
