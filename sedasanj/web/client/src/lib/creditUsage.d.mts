export function usageShares(planSeconds: number, purchasedSeconds: number): { plan: number; purchased: number; empty: boolean };
export function stepFor(minutes: number): number;
export function clampMinutes(value: number | string, min: number, max: number): number;
export function stepMinutes(current: number, direction: 1 | -1, min: number, max: number): number;
export function sliderPosition(minutes: number, min: number, max: number): number;
