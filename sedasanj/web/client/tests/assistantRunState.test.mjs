import assert from "node:assert/strict";
import test from "node:test";
import { isFreshRunSequence, orderUniqueRunEvents, withConversationRunState } from "../src/pages/assistantRunState.mjs";

test("run sequence rejects duplicates and late events", () => {
  assert.equal(isFreshRunSequence(4, 4), false);
  assert.equal(isFreshRunSequence(4, 3), false);
  assert.equal(isFreshRunSequence(4, 5), true);
});

test("snapshot replay and live buffer merge once in sequence order", () => {
  const replayed = [{ sequence: 1, event: "delta" }, { sequence: 2, event: "phase" }];
  const buffered = [{ sequence: 2, event: "phase" }, { sequence: 4, event: "done" }, { sequence: 3, event: "delta" }];
  assert.deepEqual(
    orderUniqueRunEvents(replayed, buffered).map((event) => event.sequence),
    [1, 2, 3, 4],
  );
});

test("finishing one conversation preserves another conversation's active run", () => {
  const state = { first: "run-1", second: "run-2" };
  assert.deepEqual(withConversationRunState(state, "first", null), { second: "run-2" });
  assert.deepEqual(withConversationRunState(state, "first", "pending"), { first: "pending", second: "run-2" });
});
