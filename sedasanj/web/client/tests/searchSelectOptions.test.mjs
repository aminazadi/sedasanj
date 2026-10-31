import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/searchSelectOptions.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022 },
}).outputText;
const { searchSelectOptions } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const calls = [{ value: "call-1", label: "09120000000 · 1405/08/10" }];

test("server search retains calls matched through transcript text absent from the label", () => {
  assert.deepEqual(searchSelectOptions(calls, "quotation", { remote: true }), calls);
  assert.deepEqual(searchSelectOptions(calls, "quotation"), []);
});

test("call selection omits the repeated prompt without dropping call options", () => {
  assert.deepEqual(searchSelectOptions(calls, "", {
    remote: true, emptyLabel: "انتخاب تماس مشتری", allowEmpty: false,
  }), calls);
});

test("existing assignment dropdowns preserve their optional empty selection", () => {
  assert.deepEqual(searchSelectOptions(calls, "", { emptyLabel: "بدون انتخاب" }), [
    { value: "", label: "بدون انتخاب" }, ...calls,
  ]);
});

test("local assignment search still matches keywords and Arabic letter variants", () => {
  const options = [{ value: "user-1", label: "کیان", keywords: "agent@example.test" }];
  assert.deepEqual(searchSelectOptions(options, "كيان"), options);
  assert.deepEqual(searchSelectOptions(options, "AGENT@EXAMPLE"), options);
});
