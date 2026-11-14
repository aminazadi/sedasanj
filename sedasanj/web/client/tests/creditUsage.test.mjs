import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { clampMinutes, sliderPosition, stepFor, stepMinutes, usageShares } from "../src/lib/creditUsage.mjs";

test("usage shares split the balance and handle an empty wallet", () => {
  assert.deepEqual(usageShares(0, 0), { plan: 0, purchased: 0, empty: true });
  assert.deepEqual(usageShares(60, 180), { plan: 25, purchased: 75, empty: false });
  assert.deepEqual(usageShares(-5, "x"), { plan: 0, purchased: 0, empty: true });
});

test("stepper moves by a size-aware step and respects the limits", () => {
  assert.equal(stepFor(10), 5);
  assert.equal(stepFor(300), 10);
  assert.equal(stepFor(5000), 100);
  assert.equal(stepMinutes(300, 1, 10, 1000), 310);
  assert.equal(stepMinutes(303, -1, 10, 1000), 300);
  assert.equal(stepMinutes(10, -1, 10, 1000), 10);
  assert.equal(stepMinutes(1000, 1, 10, 1000), 1000);
  assert.equal(clampMinutes("abc", 10, 100), 10);
});

test("slider position is monotonic and bounded", () => {
  assert.equal(sliderPosition(10, 10, 1000), 0);
  assert.equal(sliderPosition(1000, 10, 1000), 100);
  assert.ok(sliderPosition(100, 10, 1000) === 50);
});

test("credit cards keep their redesigned structure and the gateway-unavailable support action", () => {
  const topup = fs.readFileSync(new URL("../src/components/CreditTopUp.tsx", import.meta.url), "utf8");
  const picker = fs.readFileSync(new URL("../src/components/PaymentMethodPicker.tsx", import.meta.url), "utf8");
  const account = fs.readFileSync(new URL("../src/pages/Account.tsx", import.meta.url), "utf8");
  assert.match(topup, /topup-stepper/);
  assert.match(topup, /topup-summary/);
  // Dragging the slider must not hit the API per tick: quotes are debounced and cached, the method list follows a settled amount.
  assert.match(topup, /quoteCache/);
  assert.match(topup, /\}, 700\);/);
  assert.match(topup, /amountToman=\{settledTotal\}/);
  assert.equal((topup.match(/credit-settings/g) ?? []).length, 1);
  assert.match(topup, /\/v1\/billing\/credit-orders/);
  assert.match(picker, /pay-empty-actions/);
  assert.match(account, /credit-hero/);
  assert.match(account, /credit-legend/);
  assert.match(account, /<TokenTopUp embedded/);
  assert.match(fs.readFileSync(new URL("../src/index.css", import.meta.url), "utf8"), /\.panel-shell \.topup-slider::-webkit-slider-runnable-track/);
});

test("integrations page keeps its guided structure", () => {
  const keys = fs.readFileSync(new URL("../src/components/ApiKeyManager.tsx", import.meta.url), "utf8");
  const pairing = fs.readFileSync(new URL("../src/components/JalaseNegarPairing.tsx", import.meta.url), "utf8");
  assert.match(keys, /key-form-foot/);
  assert.match(keys, /scope-grid/);
  assert.match(keys, /keys\.length === 0/);
  assert.match(pairing, /pair-steps/);
  assert.match(pairing, /device-list/);
});

test("API key expiry uses the shared Jalali date picker instead of the native date input", () => {
  const keys = fs.readFileSync(new URL("../src/components/ApiKeyManager.tsx", import.meta.url), "utf8");
  assert.match(keys, /JalaliDatePicker/);
  assert.doesNotMatch(keys, /type="date"/);
});

test("tasks page uses compact rows with a quick complete action and a single toolbar", () => {
  const tasks = fs.readFileSync(new URL("../src/pages/Tasks.tsx", import.meta.url), "utf8");
  assert.match(tasks, /className="task-list"/);
  assert.match(tasks, /task-check/);
  assert.match(tasks, /status: task\.status === "done" \? "open" : "done", version: task\.version/);
  assert.match(tasks, /tasks-toolbar/);
  assert.doesNotMatch(tasks, /<table/);
  assert.match(tasks, /offset > 0 \|\| \(page && page\.total > pageSize\)/);
});
