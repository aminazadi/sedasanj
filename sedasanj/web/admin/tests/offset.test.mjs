import assert from "node:assert/strict";
import test from "node:test";
import { toOffset } from "../src/lib/offset.mjs";

test("a positive integer is kept", () => {
  assert.equal(toOffset("50"), 50);
});

test("empty, negative, fractional and non-numeric values mean the first page", () => {
  for (const value of ["", "-5", "2.5", "abc", null, undefined]) assert.equal(toOffset(value), 0);
});
