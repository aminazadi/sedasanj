import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import postcss from "postcss";
import tailwind from "tailwindcss";
import tailwindConfig from "../tailwind.config.js";

// Install playwright-core or select its entry point with SIDEBAR_PLAYWRIGHT_MODULE.
const { chromium } = await import(process.env.SIDEBAR_PLAYWRIGHT_MODULE ?? "playwright-core");
const cwd = fileURLToPath(new URL("..", import.meta.url));
const bundle = await build({
  stdin: {
    contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
      import {BrowserRouter, useLocation} from 'react-router-dom'; import Layout from './src/components/Layout';
      localStorage.setItem('sedasanj.client.sidebarCollapsed', '1');
      function App() { const location = useLocation(); return <Layout><output id="route">{location.pathname}</output></Layout>; }
      createRoot(document.getElementById('root')).render(<BrowserRouter><App /></BrowserRouter>);`,
    resolveDir: cwd, loader: "tsx",
  }, bundle: true, write: false, jsx: "automatic",
  plugins: [{ name: "sidebar-fixture", setup(builder) {
    builder.onResolve({ filter: /^(\.\.\/auth|\.\/BrandLogo|\.\/ModuleUpdateBanner|\.\/QuickAssistantWidget)$/ },
      args => args.importer.endsWith("/Layout.tsx") ? { path: args.path, namespace: "fixture" } : undefined);
    builder.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: args.path === "../auth"
      ? `export const useAuth = () => ({session: {role: 'viewer', userId: 'test-user'}, logout: async () => {}});
         export const isOperator = () => false; export const isOrgAdmin = () => false; export const ROLE_LABELS = {viewer: 'Viewer'};`
      : "export const BrandLogo = () => null; export default () => null;" }));
  } }],
});
const css = await postcss([tailwind({ ...tailwindConfig, content: [join(cwd, "src/components/Layout.tsx")], corePlugins: { preflight: false } })])
  .process(await readFile(join(cwd, "src/index.css"), "utf8"), { from: undefined });
const server = createServer((request, response) => {
  response.setHeader("Content-Type", request.url === "/bundle.js" ? "text/javascript" : request.url === "/style.css" ? "text/css" : "text/html; charset=utf-8");
  response.end(request.url === "/bundle.js" ? bundle.outputFiles[0].text : request.url === "/style.css" ? css.css
    : '<html dir="rtl"><link rel="stylesheet" href="/style.css"><div id="root"></div><script src="/bundle.js"></script></html>');
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, hasTouch: true });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  const nav = page.locator("#client-desktop-menu");
  const tooltip = page.getByRole("tooltip");
  const route = page.locator("#route");
  const calls = nav.locator('a[href="/calls"]');
  await calls.hover();
  await tooltip.waitFor();
  await calls.click();
  await page.waitForFunction(() => location.pathname === "/calls");
  assert.equal(await tooltip.count(), 0, "Click must dismiss the tooltip");
  await page.mouse.move(700, 300);
  await page.keyboard.press("Tab");
  await tooltip.waitFor();
  assert.equal(await tooltip.innerText(), "پیام‌های صوتی");
  await page.keyboard.press("Escape");
  await tooltip.waitFor({ state: "detached" });
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => location.pathname === "/voicemails");
  assert.equal(await route.innerText(), "/voicemails");
  await nav.locator('a[href="/meetings"]').tap();
  await page.waitForFunction(() => location.pathname === "/meetings");
  assert.equal(await tooltip.count(), 0, "Touch must not open a tooltip");
  await nav.locator('a[href="/contacts"]').hover();
  await tooltip.waitFor();
  await page.evaluate(() => { history.back(); });
  await page.waitForFunction(() => location.pathname === "/voicemails");
  assert.equal(await tooltip.count(), 0, "History navigation must dismiss the tooltip");
  await nav.getByRole("button", { name: "باز کردن منو", exact: true }).click();
  await nav.locator('a[href="/contacts"]').click();
  await page.waitForFunction(() => location.pathname === "/contacts");
  assert.equal(await tooltip.count(), 0, "Expanded menu must not open tooltips");
  await nav.getByRole("link", { name: "مقالات و آموزش‌ها", exact: true }).click();
  await page.waitForFunction(() => location.pathname === "/help");
  assert.equal(await route.innerText(), "/help");
  await nav.locator('a[href="/calls"]').click();
  await page.waitForFunction(() => location.pathname === "/calls");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "نمایش منو", exact: true }).click();
  const mobile = page.locator("#client-mobile-menu");
  await mobile.getByRole("link", { name: "مقالات و آموزش‌ها", exact: true }).tap();
  await page.waitForFunction(() => location.pathname === "/help");
  assert.equal(await route.innerText(), "/help");
  await mobile.waitFor({ state: "hidden" });
  assert.equal(await tooltip.count(), 0);
  console.log("PASS: hover, single click/tap, keyboard focus/Enter/Escape, history, expanded menu, mobile drawer");
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
