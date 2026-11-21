import assert from "node:assert/strict";
import { readFile, access } from "node:fs/promises";
import test from "node:test";

const layout = await readFile(new URL("../src/components/Layout.tsx", import.meta.url), "utf8");
const app = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const settings = await readFile(new URL("../src/pages/AccountSettings.tsx", import.meta.url), "utf8");
const panelAccess = await readFile(new URL("../src/lib/panelAccess.ts", import.meta.url), "utf8");
const install = await readFile(new URL("../src/pages/JalaseNegarInstall.tsx", import.meta.url), "utf8");

test("the stand-alone jalase-menu sidebar item and page are gone", async () => {
  assert.doesNotMatch(layout, /"\/jalase-menu"/);
  assert.doesNotMatch(app, /JalaseMenu"/);
  await assert.rejects(access(new URL("../src/pages/JalaseMenu.tsx", import.meta.url)));
});

test("old /jalase-menu links still resolve, redirected into account settings", () => {
  assert.match(app, /path="\/jalase-menu" element=\{<Navigate to="\/account-settings\?tab=jalase" replace \/>\}/);
});

test("the sidebar has a dedicated \"جلسه‌نگار\" group with general minutes and the install guide", () => {
  const groupIndex = layout.indexOf('label: "جلسه‌نگار"');
  assert.notEqual(groupIndex, -1);
  const groupSlice = layout.slice(groupIndex, groupIndex + 400);
  assert.match(groupSlice, /to: "\/meetings", label: "صورت‌جلسات عمومی"/);
  assert.match(groupSlice, /to: "\/jalase-negar-install"/);
});

test("org categories are injected next to general minutes inside that group", () => {
  assert.match(layout, /item\.to === "\/meetings" \? \[item, \.\.\.jalaseItems\]/);
});

test("account settings exposes a dedicated جلسه‌نگار tab with the menu visibility settings for admins only", () => {
  assert.match(settings, /id: "jalase", label: "جلسه‌نگار"/);
  assert.match(settings, /orgAdmin \? <JalaseNegarMenuSettings \/> : null/);
  assert.match(panelAccess, /jalase: "integrations"/);
});

test("the install guide page loads the public downloads endpoint and links back to the pairing tab", () => {
  assert.match(install, /request<AppDownloads>\("\/v1\/jalase-negar\/downloads"/);
  assert.match(install, /to="\/account-settings\?tab=jalase"/);
});
