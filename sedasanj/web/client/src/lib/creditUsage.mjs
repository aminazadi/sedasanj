// Pure helpers for the credit page: balance split and minute stepping.

/** Percentages (0-100, rounded to 0.1) of plan minutes and prepaid minutes in the balance. */
export function usageShares(planSeconds, purchasedSeconds) {
  const plan = Math.max(0, Number(planSeconds) || 0);
  const purchased = Math.max(0, Number(purchasedSeconds) || 0);
  const total = plan + purchased;
  if (total <= 0) return { plan: 0, purchased: 0, empty: true };
  const planShare = Math.round((plan / total) * 1000) / 10;
  return { plan: planShare, purchased: Math.round((100 - planShare) * 10) / 10, empty: false };
}

/** Step size grows with the amount so the +/- buttons stay useful from 10 to 1,000,000 minutes. */
export function stepFor(minutes) {
  if (minutes >= 10_000) return 1000;
  if (minutes >= 1000) return 100;
  if (minutes >= 100) return 10;
  return 5;
}

export function clampMinutes(value, min, max) {
  const number = Math.trunc(Number(value)) || 0;
  return Math.min(Math.max(number, min), max);
}

/** Next value for the stepper buttons; direction is +1 or -1. */
export function stepMinutes(current, direction, min, max) {
  const step = stepFor(direction < 0 ? Math.max(current - 1, 0) : current);
  const snapped = direction < 0 ? Math.ceil(current / step) * step - step : Math.floor(current / step) * step + step;
  return clampMinutes(snapped, min, max);
}

/** Position (0-100) of a value on the quick slider, logarithmic because the range spans decades. */
export function sliderPosition(minutes, min, max) {
  const low = Math.log(Math.max(min, 1));
  const high = Math.log(Math.max(max, min + 1));
  const value = Math.log(Math.min(Math.max(minutes, min), max));
  return Math.round(((value - low) / (high - low)) * 1000) / 10;
}
