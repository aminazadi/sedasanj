import assert from "node:assert/strict";
import test from "node:test";
import { isMobileSpeechClient, joinText, mergeFinalPhrases } from "../src/lib/speechResults.mjs";

test("cumulative final results collapse to the longest phrase", () => {
  assert.equal(mergeFinalPhrases(["سلام", "سلام من", "سلام من امین"]), "سلام من امین");
});

test("distinct phrases are joined in order", () => {
  assert.equal(mergeFinalPhrases(["سلام", "گزارش امروز"]), "سلام گزارش امروز");
});

test("repeated or shorter echoes are dropped", () => {
  assert.equal(mergeFinalPhrases(["سلام من", "سلام من", "سلام"]), "سلام من");
  assert.equal(mergeFinalPhrases(["", "  "]), "");
});

test("joinText skips blanks", () => {
  assert.equal(joinText(" a ", "", "b"), "a b");
});

test("mobile detection", () => {
  assert.equal(isMobileSpeechClient("Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile"), true);
  assert.equal(isMobileSpeechClient("Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/120", 0), false);
});
