import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/pages/CallDetail.tsx", import.meta.url), "utf8");
const visibilityExpression = source.match(/const showProcessingDetails = ([^;]+);/)?.[1];
assert.ok(visibilityExpression);
const isVisible = new Function("hasAudioAnalysis", "call", `return ${visibilityExpression};`);

test("completed audio analysis hides both processing sections regardless of progress metadata", () => {
  for (const processing of [false, true]) {
    for (const progress_pct of [0, 99, 100]) {
      assert.equal(isVisible(true, { status: "complete", processing, progress_pct }), false);
    }
  }
  assert.match(source, /: showProcessingDetails \? <ProcessingCard\b/);
  assert.match(source, /\{showProcessingDetails \? <ProcessingTimeline\b/);
});

test("ongoing, failed, canceled and restarted analyses keep processing details available", () => {
  for (const status of ["received", "stored", "transcribing", "transcribed", "correcting", "emotion_queued", "emotion_analyzing", "analyzing", "analyzed", "billed", "notified", "failed_retryable", "failed_terminal", "canceled"]) {
    assert.equal(isVisible(true, { status }), true, status);
  }
});

test("calls without audio analysis do not show processing sections", () => {
  for (const status of ["received", "complete", "failed_terminal", "canceled"]) {
    assert.equal(isVisible(false, { status }), false, status);
  }
});
