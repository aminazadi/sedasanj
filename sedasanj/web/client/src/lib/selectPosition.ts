interface TriggerRect {
  top: number;
  bottom: number;
  right: number;
  width: number;
}

/** Keep the menu aligned to its RTL trigger and inside the viewport. */
export function selectPosition(rect: TriggerRect, viewportWidth: number, viewportHeight: number) {
  const padding = 8;
  const gap = 4;
  const width = Math.min(rect.width, Math.max(0, viewportWidth - padding * 2));
  const below = Math.max(0, viewportHeight - rect.bottom - gap - padding);
  const above = Math.max(0, rect.top - gap - padding);
  const upwards = below < 280 && above > below;
  return {
    left: Math.max(padding, Math.min(rect.right - width, viewportWidth - width - padding)),
    width,
    maxHeight: Math.min(280, upwards ? above : below),
    ...(upwards
      ? { bottom: Math.max(padding, viewportHeight - rect.top + gap) }
      : { top: Math.max(padding, rect.bottom + gap) }),
  };
}
