import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { initialResourceState, resourceReducer } from "../../shared/lib/resourceState.ts";

test("first load is initial and keeps no data", () => {
  const state = resourceReducer(initialResourceState(), { type: "start", id: 1, silent: false });
  assert.equal(state.status, "initial");
  assert.equal(state.data, undefined);
});

test("refetch keeps the previous data and reports refreshing", () => {
  let state = resourceReducer(initialResourceState(), { type: "start", id: 1, silent: false });
  state = resourceReducer(state, { type: "success", id: 1, data: ["a"] });
  state = resourceReducer(state, { type: "start", id: 2, silent: false });
  assert.equal(state.status, "refreshing");
  assert.deepEqual(state.data, ["a"]);
});

test("a stale response is ignored", () => {
  let state = resourceReducer(initialResourceState(), { type: "start", id: 1, silent: false });
  state = resourceReducer(state, { type: "start", id: 2, silent: false });
  state = resourceReducer(state, { type: "success", id: 1, data: "old" });
  assert.equal(state.data, undefined);
  state = resourceReducer(state, { type: "success", id: 2, data: "new" });
  assert.equal(state.data, "new");
  assert.equal(state.status, "ready");
});

test("a silent reload does not change status", () => {
  let state = resourceReducer(initialResourceState(), { type: "start", id: 1, silent: false });
  state = resourceReducer(state, { type: "success", id: 1, data: 1 });
  state = resourceReducer(state, { type: "start", id: 2, silent: true });
  assert.equal(state.status, "ready");
  state = resourceReducer(state, { type: "success", id: 2, data: 2 });
  assert.equal(state.data, 2);
});

test("a failure keeps data and a stale failure is ignored", () => {
  let state = resourceReducer(initialResourceState(), { type: "start", id: 1, silent: false });
  state = resourceReducer(state, { type: "success", id: 1, data: "kept" });
  state = resourceReducer(state, { type: "start", id: 2, silent: false });
  state = resourceReducer(state, { type: "start", id: 3, silent: false });
  state = resourceReducer(state, { type: "failure", id: 2, error: "stale" });
  assert.equal(state.error, null);
  state = resourceReducer(state, { type: "failure", id: 3, error: "boom" });
  assert.equal(state.status, "error");
  assert.equal(state.error, "boom");
  assert.equal(state.data, "kept");
});

test("skeleton animation is disabled for reduced motion", () => {
  const css = readFileSync(new URL("../../shared/styles/skeleton.css", import.meta.url), "utf8");
  assert.match(css, /prefers-reduced-motion: reduce[\s\S]*\.skeleton::after[\s\S]*animation: none/);
});

test("pages do not blank their data on refetch or show the brand loader inline", () => {
  const read = (path) => readFileSync(new URL(`../src/pages/${path}`, import.meta.url), "utf8");
  for (const page of ["Calls.tsx", "Overview.tsx", "OperatorScores.tsx"]) {
    const source = read(page);
    assert.doesNotMatch(source, /setData\(null\)|setReport\(null\)|setRecent\(null\)/, `${page} nulls its data on refetch`);
    assert.doesNotMatch(source, /<Loading\b/, `${page} shows the generic loader`);
  }
  const widgets = readFileSync(new URL("../src/components/Widgets.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(widgets, /BrandLoader/, "Loading must not render the animated brand logo");
});
