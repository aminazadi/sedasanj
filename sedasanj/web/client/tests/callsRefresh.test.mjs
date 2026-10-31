import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/pages/Calls.tsx", import.meta.url), "utf8");
const table = source.slice(source.indexOf("const CallsTableSection = memo("), source.indexOf("export default function Calls()"));

test("manual refresh stays inside the table and reuses the filtered resource", () => {
  const button = table.match(/<button\s[^>]*onClick=\{\(\) => calls\.reload\(\)\}[^>]*>/s)?.[0];
  assert.ok(button);
  assert.match(button, /disabled=\{calls.loading\}/);
  assert.match(button, /aria-busy=\{calls.loading\}/);
  assert.match(button, /aria-label=\{calls.loading \? "در حال بروزرسانی تماس‌ها" : "بروزرسانی تماس‌ها"\}/);
  assert.match(table, /createPortal\(/);
  assert.match(source, /<div ref=\{setRefreshTarget\}/);
  assert.doesNotMatch(table, />بروزرسانی</);
  assert.match(table, /query\(\{ \.\.\.applied, offset: pageIndex \* PAGE_SIZE, limit: PAGE_SIZE \}\)/);
  assert.match(table, /<ErrorBox message=\{calls.error \?\? actionError\}/);
  assert.doesNotMatch(button, /setSearchParams|setReloadKey|location/);
});
