import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { permissionsKey, sameSession } from "../src/lib/sameSession.ts";

const base = { userId: "u1", tenantId: "t1", role: "org_admin", panelPermissions: ["calls", "kpi"] };

test("an identical session with a fresh permission array is the same session", () => {
  assert.equal(sameSession(base, { ...base, panelPermissions: ["calls", "kpi"] }), true);
});

test("changed role, permissions or user are different sessions", () => {
  assert.equal(sameSession(base, { ...base, role: "operator" }), false);
  assert.equal(sameSession(base, { ...base, panelPermissions: ["calls"] }), false);
  assert.equal(sameSession(base, { ...base, panelPermissions: null }), false);
  assert.equal(sameSession(base, null), false);
  assert.equal(sameSession(null, null), true);
});

test("permissionsKey is stable across array identities", () => {
  assert.equal(permissionsKey(["a", "b"]), permissionsKey(["a", "b"]));
  assert.notEqual(permissionsKey(null), permissionsKey([]));
});

test("auth refresh keeps the session reference and Overview keys on permissions text", () => {
  const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
  assert.match(read("../src/auth.tsx"), /sameSession\(prev, next\) \? prev : next/);
  const overview = read("../src/pages/Overview.tsx");
  assert.doesNotMatch(overview, /\[session\?\.panelPermissions,/);
  assert.match(overview, /const live = dashboard\.data \?\? null;/);
});
