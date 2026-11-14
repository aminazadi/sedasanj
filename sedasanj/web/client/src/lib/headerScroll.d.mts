export type HeaderScrollState = { y: number; anchor: number; direction: number; hidden: boolean };
export function nextHeaderScroll(state: HeaderScrollState, scrollY: number): HeaderScrollState;
