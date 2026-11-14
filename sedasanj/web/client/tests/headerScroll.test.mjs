import assert from "node:assert/strict";
import test from "node:test";
import { nextHeaderScroll } from "../src/lib/headerScroll.mjs";
const initial = { y: 0, anchor: 0, direction: 0, hidden: false };

test("header hides down, ignores jitter and returns after upward movement", () => {
  let state = nextHeaderScroll(initial, 150);
  assert.equal(state.hidden, true);
  state = nextHeaderScroll(state, 147);
  assert.equal(state.hidden, true);
  state = nextHeaderScroll(state, 139);
  assert.equal(state.hidden, false);
  state = nextHeaderScroll(state, 142);
  assert.equal(state.hidden, false);
  state = nextHeaderScroll(state, 153);
  assert.equal(state.hidden, true);
});
test("header stays visible near the top and handles overscroll", () => {
  let state = nextHeaderScroll(initial, 200);
  state = nextHeaderScroll(state, 79);
  assert.equal(state.hidden, false);
  state = nextHeaderScroll(state, -20);
  assert.equal(state.y, 0);
  assert.equal(state.hidden, false);
  assert.equal(nextHeaderScroll(state, 60).hidden, false);
});
