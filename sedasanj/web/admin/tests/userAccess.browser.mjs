import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Run with Node 22+; CHROME_BIN overrides the local browser executable.
const cwd = fileURLToPath(new URL("..", import.meta.url));
const browser = process.env.CHROME_BIN ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const port = process.env.USER_ACCESS_TEST_PORT ?? "5196";
const url = `http://127.0.0.1:${port}/tests/fixtures/user-access.html`;
const profile = await mkdtemp(join(tmpdir(), "sedasanj-user-access-"));
const server = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--port", port, "--strictPort"], { cwd, stdio: "ignore" });
let chrome;
let socket;
const pause = () => new Promise(resolve => setTimeout(resolve, 100));
async function until(read, description) {
  for (let attempt = 0; attempt < 300; attempt++) {
    try { const value = await read(); if (value) return value; } catch { /* Wait for the service. */ }
    await pause();
  }
  throw new Error(`Timed out waiting for ${description}`);
}
try {
  await until(async () => (await fetch(url)).ok, "Vite");
  chrome = spawn(browser, [
    "--headless", "--no-sandbox", "--disable-gpu", "--no-first-run",
    `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank",
  ], { stdio: "ignore" });
  const debugPort = await until(async () => (await readFile(join(profile, "DevToolsActivePort"), "utf8")).split("\n")[0], "Chrome");
  const tabs = await (await fetch(`http://127.0.0.1:${debugPort}/json/list`)).json();
  socket = new WebSocket(tabs.find(tab => tab.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const handler = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) handler?.reject(new Error(message.error.message));
    else handler?.resolve(message.result);
  };
  function cdp(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });
  }
  await cdp("Page.enable");
  for (const width of [1440, 390]) {
    await cdp("Emulation.setDeviceMetricsOverride", { width, height: 1100, deviceScaleFactor: 1, mobile: false });
    await cdp("Page.navigate", { url: `${url}?viewport=${width}` });
    const result = await until(async () => {
      const value = await cdp("Runtime.evaluate", {
        expression: 'document.getElementById("results")?.textContent', returnByValue: true,
      });
      return value.result?.value?.startsWith("{") ? value.result.value : null;
    }, "user access forms");
    const report = JSON.parse(result);
    assert.equal(report.passed, true, report.error);
    console.log(`PASS ${width}px: roles, sensitive proof, synced extensions, custom values, and errors`);
  }
} finally {
  socket?.close();
  chrome?.kill("SIGTERM");
  server.kill("SIGTERM");
  if (chrome && chrome.exitCode === null) await new Promise(resolve => chrome.once("exit", resolve));
  await rm(profile, { recursive: true, force: true });
}
