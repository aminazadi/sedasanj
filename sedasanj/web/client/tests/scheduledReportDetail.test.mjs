import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import ts from "typescript";
import { reportArchiveUrl, reportDetailUrl, reportTabFromSearch } from "../src/lib/scheduledReportNavigation.mjs";

const source = fs.readFileSync(new URL("../src/pages/ScheduledReportDetail.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText;
const fixture = { id: "run-1", name: "Report", title: "Daily report", status: "succeeded", content: "Saved text", coverage: {}, charts: [], sources: [{ call_id: "call-1" }], from_date: "2026-11-01", to_date: "2026-11-02" };

function render({ detail = fixture, tab = "report", draft = null, error = null } = {}) {
  const effects = [];
  const stateValues = [draft, null, tab === "report"];
  const reloads = [];
  const params = new URLSearchParams(`report=definition-1&offset=20&detail_tab=${tab}`);
  let changedParams, fetcher;
  const stubs = new Map();
  const component = name => { if (!stubs.has(name)) stubs.set(name, () => null); return stubs.get(name); };
  const require = name => {
    if (name === "react") return { ...React, useState: () => [stateValues.shift(), () => {}], useEffect: effect => effects.push(effect) };
    if (name === "react-router-dom") return { Link: component("Link"), useParams: () => ({ runId: "run-1" }), useSearchParams: () => [params, next => { changedParams = next; }] };
    if (name.endsWith("/useResource")) return { useResource: fn => { fetcher = fn; return { data: detail, error, reload: options => reloads.push(options) }; } };
    if (name === "../api") return { fmt: { int: String, dateTime: String }, request: (path, options) => ({ path, options }) };
    if (name.endsWith("scheduledReportNavigation.mjs")) return { REPORT_TABS: ["report", "sources", "criteria"], reportArchiveUrl, reportTabFromSearch };
    return new Proxy({}, { get: (_, key) => key === "reportPeriod" ? () => ({ window: "period", timezone: "Asia/Tehran" }) : key === "DOCUMENT_ACTION_CLASS" ? "action" : component(key === "default" ? name.split("/").at(-1) : key) });
  };
  const exports = {};
  new Function("React", "require", "exports", compiled)(React, require, exports);
  const tree = exports.default();
  const nodes = [];
  function visit(node) { if (!node || typeof node !== "object") return; if (Array.isArray(node)) return node.forEach(visit); nodes.push(node); visit(node.props?.children); visit(node.props?.actions); }
  visit(tree);
  const find = name => nodes.find(node => node.type === component(name));
  return { tree, nodes, find, effects, reloads, fetcher, get changedParams() { return changedParams; } };
}

test("detail URLs migrate old links and preserve archive filters without leaking detail tabs", () => {
  const params = new URLSearchParams("run=old&tab=settings&report=r&status=failed&trigger=manual&offset=20&detail_tab=sources");
  const target = new URL(reportDetailUrl("new/id", params), "https://example.test");
  assert.equal(target.pathname, "/scheduled-reports/runs/new%2Fid");
  assert.equal(target.searchParams.has("run"), false);
  const back = new URL(reportArchiveUrl(target.searchParams), target.origin);
  assert.equal(back.searchParams.get("tab"), "archive");
  for (const key of ["report", "status", "trigger", "offset"]) assert.equal(back.searchParams.get(key), params.get(key));
  assert.equal(back.searchParams.has("detail_tab"), false);
  assert.equal(reportTabFromSearch(new URLSearchParams("detail_tab=unknown")), "report");
});

test("completed detail contains document actions and editor without archive or coverage clutter", () => {
  const view = render({ draft: "Edited text" });
  assert.equal(view.nodes.some(node => node.type === "table"), false);
  assert.equal(view.find("ReportCoverage"), undefined);
  assert.equal(view.find("ReportDocumentActions").props.content, "Edited text");
  assert.equal(view.find("DocumentEditor").props.expectedContent, "Saved text");
  assert.equal(view.find("DocumentEditor").props.path, "/v1/scheduled-reports/runs/run-1");
  view.find("DocumentEditor").props.onSaved("New text");
  assert.deepEqual(view.reloads, [{ silent: true }]);
  const tabs = view.find("DocumentTabs");
  assert.equal(tabs.props.align, "start");
  tabs.props.onChange("criteria");
  assert.equal(view.changedParams.get("detail_tab"), "criteria");
  assert.equal(view.changedParams.get("offset"), "20");
});

test("sources are visible only on their own URL-selected tab", () => {
  const view = render({ tab: "sources" });
  assert.ok(view.find("ReportCoverage"));
  assert.equal(view.find("DocumentEditor"), undefined);
  assert.ok(view.nodes.some(node => node.props?.to === "/calls/call-1"));
});

test("only active reports poll and detail fetch forwards cancellation", () => {
  const previousWindow = globalThis.window;
  let interval, cleared;
  globalThis.window = { setInterval: (fn, ms) => { interval = { fn, ms }; return 42; }, clearInterval: id => { cleared = id; } };
  try {
    const completed = render();
    completed.effects.forEach(effect => effect());
    assert.equal(interval, undefined);
    const active = render({ detail: { ...fixture, status: "running", content: null } });
    const cleanups = active.effects.map(effect => effect()).filter(Boolean);
    assert.equal(interval.ms, 10000);
    interval.fn();
    assert.deepEqual(active.reloads, [{ silent: true }]);
    cleanups.forEach(cleanup => cleanup());
    assert.equal(cleared, 42);
    const signal = new AbortController().signal;
    assert.deepEqual(active.fetcher(signal), { path: "/v1/scheduled-reports/runs/run-1", options: { signal } });
  } finally { globalThis.window = previousWindow; }
});

test("failed loads retain navigation and stale data from another run is hidden", () => {
  for (const detail of [undefined, { ...fixture, id: "another-run" }]) {
    const view = render({ detail: detail ?? null, error: "Unavailable" });
    assert.equal(view.find("DocumentEditor"), undefined);
    assert.equal(view.find("ErrorBox").props.message, "Unavailable");
    assert.ok(view.find("Link").props.to.startsWith("/scheduled-reports?"));
  }
});

test("report export uses icon actions, current text and charts without coverage cards", () => {
  const moduleSource = fs.readFileSync(new URL("../src/components/ScheduledReportDocument.tsx", import.meta.url), "utf8");
  const js = ts.transpileModule(moduleSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText;
  const exports = {};
  const require = name => name === "@cbi/web-shared/theme" ? { chart: {} } : name.endsWith("DocumentActions") ? { default: "Actions" } : name.endsWith("MarkdownMessage") ? { default: "Markdown" } : { AssistantCharts: "Charts" };
  new Function("React", "require", "exports", js)(React, require, exports);
  const tree = exports.ReportDocumentActions({ run: fixture, content: "Edited text", period: { window: "Period", timezone: "Asia/Tehran" } });
  assert.equal(tree.props.iconOnly, true);
  assert.equal(tree.props.title, fixture.title);
  assert.deepEqual(tree.props.children.map(child => child.type), ["Markdown", "Charts"]);
  assert.equal(tree.props.children[0].props.content, "Edited text");
  assert.deepEqual(tree.props.children[1].props.charts, fixture.charts);
});
