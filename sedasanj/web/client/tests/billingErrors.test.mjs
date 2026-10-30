import assert from "node:assert/strict";
import test from "node:test";
import { BILLING_ERRORS, billingErrorMessage } from "../src/lib/billingErrors.mjs";

test("a known code maps to Persian text that names an action", () => {
  const text = billingErrorMessage("subscription_exists", "English server text", "fallback");
  assert.equal(text, BILLING_ERRORS.subscription_exists);
  assert.match(text, /تغییر پلن/);
});

test("an unknown code keeps a Persian server message", () => {
  assert.equal(billingErrorMessage("other", "این ایمیل قبلاً ثبت شده است.", "x"), "این ایمیل قبلاً ثبت شده است.");
});

test("an unknown code with an English message uses the fallback", () => {
  assert.equal(billingErrorMessage("other", "plan code already exists", "ساخت سفارش انجام نشد."), "ساخت سفارش انجام نشد.");
});

test("every mapped message is Persian", () => {
  for (const text of Object.values(BILLING_ERRORS)) assert.match(text, /[؀-ۿ]/);
});
