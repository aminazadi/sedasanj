import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { build } from "esbuild";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PAGE_SIZES, pageSize, tableOffset, withPageSize } from "../../shared/lib/tablePagination.mjs";

const require = createRequire(import.meta.url);
async function sourceModule(relative) {
  const result = await build({ entryPoints: [new URL(relative, import.meta.url).pathname], bundle: true, write: false, format: "esm", platform: "node", jsx: "automatic", plugins: [{ name: "shared-react", setup(build) { build.onResolve({ filter: /^(react|react-dom)(\/.*)?$/ }, (args) => ({ path: pathToFileURL(require.resolve(args.path)).href, external: true })); } }], nodePaths: [new URL("../node_modules", import.meta.url).pathname] });
  const directory = mkdtempSync(join(tmpdir(), "ss-table-test-"));
  const output = join(directory, "component.mjs");
  writeFileSync(output, result.outputFiles[0].text);
  try { return await import(pathToFileURL(output).href); } finally { rmSync(directory, { recursive: true }); }
}
const { tablePreferences, tableOffsetState } = await sourceModule("../../shared/lib/useTablePreferences.ts");
const { PaginatedTable } = await sourceModule("../../shared/components/PaginatedTable.tsx");

function storage() {
  const values = new Map();
  globalThis.localStorage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test("only the supported sizes are accepted, including 200", () => {
  assert.deepEqual(PAGE_SIZES, [10, 25, 50, 100, 200]);
  for (const size of PAGE_SIZES) assert.equal(pageSize(String(size)), size);
  for (const value of [null, "", "201", "-1", "Infinity", "25.5", "abc"]) assert.equal(pageSize(value), 25);
  for (const value of ["NaN", "-1", "1.5", "1e30"]) assert.equal(tableOffset(value), 0);
});

test("changing size resets every table position and preserves filters and tabs", () => {
  const params = new URLSearchParams("page=3&offset=50&user_offset=25&goals_page=2&ledger=50&orders=50&tab=users&q=Ali&from=2026-10-01");
  const next = withPageSize(params, 200);
  assert.deepEqual(Object.fromEntries(next), { tab: "users", q: "Ali", from: "2026-10-01", page_size: "200" });
  assert.equal(params.get("page"), "3");
});

test("URL wins over storage; an explicit selection survives reopening and is isolated per screen", () => {
  storage();
  let next;
  tablePreferences(new URLSearchParams(), (params) => { next = params; }, "client:/calls")[1](200);
  assert.equal(next.get("page_size"), "200");
  assert.equal(tablePreferences(new URLSearchParams(), () => {}, "client:/calls")[0], 200);
  assert.equal(tablePreferences(new URLSearchParams("page_size=50"), () => {}, "client:/calls")[0], 50);
  assert.equal(tablePreferences(new URLSearchParams(), () => {}, "admin:/calls")[0], 25);
});

test("blocked storage still allows selection and URL persistence", () => {
  globalThis.localStorage = { getItem() { throw Error("blocked"); }, setItem() { throw Error("blocked"); } };
  let next;
  const [size, setSize] = tablePreferences(new URLSearchParams("q=test&offset=50"), (params) => { next = params; }, "blocked");
  assert.equal(size, 25);
  assert.doesNotThrow(() => setSize(100));
  assert.equal(next.toString(), "q=test&page_size=100");
});

test("table positions survive reload and preserve other query values", () => {
  let next;
  const [offset, setOffset] = tableOffsetState(new URLSearchParams("user_offset=50&page_size=200&tab=users"), (params) => { next = params; }, "user_offset");
  assert.equal(offset, 50);
  setOffset((value) => value + 200);
  assert.equal(next.get("user_offset"), "250");
  assert.equal(next.get("page_size"), "200");
  assert.equal(next.get("tab"), "users");
});

test("in-memory tables display up to 200 actual rows and retain headers and controls", () => {
  const children = [createElement("thead", { key: "head" }, createElement("tr", null, createElement("th", null, "Name"))), createElement("tbody", { key: "body" }, Array.from({ length: 237 }, (_, i) => createElement("tr", { key: i }, createElement("td", null, `row-${i}`))))];
  const render = (size, offset) => renderToStaticMarkup(createElement(PaginatedTable, { size, offset, onOffset() {}, onSize() {}, children }));
  const first = render(200, 0);
  assert.equal((first.match(/<tr>/g) ?? []).length, 201);
  assert.match(first, /row-199/);
  assert.doesNotMatch(first, /row-200/);
  const last = render(200, 200);
  assert.equal((last.match(/<tr>/g) ?? []).length, 38);
  assert.match(last, /row-236/);
  const reduced = render(200, 99999);
  assert.match(reduced, /row-236/);
  assert.match(render(25, 0), /aria-haspopup="listbox"/);
  assert.match(render(25, 0), /aria-expanded="false"/);
  assert.match(render(200, 0), /۲۰۰/);
});
