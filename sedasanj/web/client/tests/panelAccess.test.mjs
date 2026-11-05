import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/panelAccess.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { canVisitPanel, hasPanelAccess, SETTINGS_ACCESS, panelHome } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const limited = { role: "org_admin", panelPermissions: ["calls", "users"] };

test("restricted admins cannot reach unselected sections through direct or nested URLs", () => {
  for (const path of ["/", "/meetings", "/meetings/123", "/contacts", "/assistant", "/scheduled-reports/runs/1", "/account", "/account-settings/data/history"]) {
    assert.equal(canVisitPanel(limited, path), false, path);
  }
  assert.equal(canVisitPanel(limited, "/calls/123"), true);
  assert.equal(canVisitPanel(limited, "/voicemails"), true);
});

test("account settings honor the tab query and retain only selected sections", () => {
  assert.equal(canVisitPanel(limited, "/account-settings"), true);
  for (const [tab, section] of Object.entries(SETTINGS_ACCESS)) {
    assert.equal(canVisitPanel(limited, "/account-settings", `?tab=${tab}`), section === "users");
  }
  assert.equal(canVisitPanel(limited, "/kpi-settings"), false);
});

test("empty grants keep profile and help available without granting panel sections", () => {
  const empty = { role: "org_admin", panelPermissions: [] };
  for (const path of ["/profile", "/help", "/help/errors/panel_access_denied"]) assert.equal(canVisitPanel(empty, path), true);
  assert.equal(canVisitPanel(empty, "/account-settings"), false);
  assert.equal(hasPanelAccess(empty, "calls"), false);
});


test("login lands on the first permitted section when dashboard access is absent", () => {
  assert.equal(panelHome(limited), "/calls");
  assert.equal(panelHome({ role: "org_admin", panelPermissions: [] }), "/profile");
});
