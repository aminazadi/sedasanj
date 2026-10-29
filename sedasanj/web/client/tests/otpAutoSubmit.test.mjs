import assert from "node:assert/strict";
import test from "node:test";
import ts from "typescript";

const sourcePath = new URL("../../shared/lib/otp.ts", import.meta.url);
const source = await (await import("node:fs/promises")).readFile(sourcePath, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const otp = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("OTP completion accepts exactly six Latin digits", () => {
  assert.equal(otp.isCompleteOtp("123456"), true);
  assert.equal(otp.isCompleteOtp("12345"), false);
  assert.equal(otp.isCompleteOtp("1234567"), false);
});

test("OTP normalization supports Persian and Arabic digits", () => {
  assert.equal(otp.normalizeOtp("۱۲٣-۴۵۶"), "123456");
  assert.equal(otp.normalizeOtp("۱۲۳۴۵۶۷"), "123456");
});
