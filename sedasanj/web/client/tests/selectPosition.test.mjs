import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/selectPosition.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022 },
}).outputText;
const { selectPosition } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("aligns the detached menu below its RTL trigger", () => {
  assert.deepEqual(selectPosition({ top: 100, bottom: 140, right: 500, width: 300 }, 900, 800), {
    left: 200, width: 300, maxHeight: 280, top: 144,
  });
});

test("opens above the bottom row instead of clipping at the viewport", () => {
  assert.deepEqual(selectPosition({ top: 700, bottom: 740, right: 500, width: 300 }, 900, 800), {
    left: 200, width: 300, maxHeight: 280, bottom: 104,
  });
});

test("constrains wide menus and scrolling content on small screens", () => {
  const position = selectPosition({ top: 40, bottom: 80, right: 600, width: 500 }, 320, 240);
  assert.deepEqual(position, { left: 8, width: 304, maxHeight: 148, top: 84 });
});

test("recomputes placement when the trigger moves during scrolling", () => {
  const rect = { top: 600, bottom: 640, right: 500, width: 300 };
  assert.equal(selectPosition(rect, 900, 800).bottom, 204);
  assert.equal(selectPosition({ ...rect, top: 100, bottom: 140 }, 900, 800).top, 144);
});
