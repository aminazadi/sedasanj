// Accumulate movement from the last direction change to ignore trackpad jitter.
export function nextHeaderScroll(state, scrollY) {
  const y = Math.max(0, scrollY);
  const direction = Math.sign(y - state.y);
  const anchor = direction && direction !== state.direction ? state.y : state.anchor;
  const hidden = y <= 80 ? false : Math.abs(y - anchor) >= 10 ? direction > 0 : state.hidden;
  return { y, anchor, direction: direction || state.direction, hidden };
}
