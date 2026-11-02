import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/pages/Meetings.tsx", import.meta.url), "utf8");
const table = source.slice(source.indexOf("const MeetingsTableSection = memo("), source.indexOf("export default function Meetings()"));

test("manual refresh stays inside the table and reuses the filtered resource", () => {
  const button = table.match(/<button\s[^>]*onClick=\{\(\) => meetings\.reload\(\)\}[^>]*>/s)?.[0];
  assert.ok(button);
  assert.match(button, /disabled=\{meetings.loading\}/);
  assert.match(button, /aria-busy=\{meetings.loading\}/);
  assert.match(button, /aria-label=\{meetings.loading \? "در حال بروزرسانی جلسات" : "بروزرسانی جلسات"\}/);
  assert.match(table, /createPortal\(/);
  assert.match(source, /<div ref=\{setRefreshTarget\}/);
  assert.doesNotMatch(table, />بروزرسانی</);
  assert.match(table, /query\(\{ \.\.\.applied, page: pageIndex \+ 1, page_size: PAGE_SIZE \}\)/);
  assert.match(table, /<ErrorBox message=\{meetings.error \?\? actionError\}/);
  assert.doesNotMatch(button, /setSearchParams|setReloadKey|location/);
});

test("rows poll every 3 seconds only while a meeting is receiving or processing", () => {
  assert.match(table, /items\.some\(\(meeting\) => isMeetingActive\(meeting\.status\)\)/);
  assert.match(table, /meetings\.reload\(\{ silent: true \}\), POLL_INTERVAL_MS/);
  assert.match(source, /POLL_INTERVAL_MS = 3000/);
});

test("filters live in the URL and the owner filter is admin only", () => {
  assert.match(source, /searchFromMeetingFilters\(/);
  assert.match(source, /hidden: !orgAdmin/);
  assert.match(source, /useSearchParams\(\)/);
});
