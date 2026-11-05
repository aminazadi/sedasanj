import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import React from "react";
import ts from "typescript";
const source = fs.readFileSync(new URL("../src/components/DocumentTabs.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React } }).outputText;
const exports = {};
new Function("React", "exports", compiled)(React, exports);
const options = ["minutes", "transcript", "speakers"].map(value => ({ value, label: value }));
test("right-aligned tabs retain selection and one keyboard entry point", () => {
  const tree = exports.default({ value: "transcript", options, onChange() {}, label: "Meeting sections", align: "start" });
  assert.match(tree.props.className, /^me-auto /);
  assert.deepEqual(tree.props.children.map(button => button.props.tabIndex), [-1, 0, -1]);
  assert.equal(tree.props.children[1].props["aria-selected"], true);
});
test("RTL arrows wrap and Home/End update both selection and focus", () => {
  for (const [index, key, target] of [[0, "ArrowRight", 2], [2, "ArrowLeft", 0], [1, "Home", 0], [1, "End", 2]]) {
    let selected, focused, prevented = false;
    const tree = exports.default({ value: options[index].value, options, onChange(value) { selected = value; }, label: "Meeting sections", align: "start" });
    tree.props.children[index].props.onKeyDown({ key, preventDefault() { prevented = true; }, currentTarget: { parentElement: { querySelectorAll() { return options.map((_, i) => ({ focus() { focused = i; } })); } } } });
    assert.equal(selected, options[target].value);
    assert.equal(focused, target);
    assert.equal(prevented, true);
  }
});
