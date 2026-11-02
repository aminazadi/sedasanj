import office from "../assets/manager-office-line-art.webp";
import emptyState from "../assets/empty-state.webp";
import allClear from "../assets/all-clear.webp";
import trendEmpty from "../assets/trend-empty.webp";
import goal from "../assets/goal.webp";

export type PageArt = { src: string; fit: "illustration" | "backdrop" };

const DASHBOARD_ART: PageArt = { src: office, fit: "backdrop" };

export const EMPTY_STATE_ART = emptyState;
/** Nothing needs attention: a completed checklist. */
export const ALL_CLEAR_ART = allClear;
/** Not enough points to draw a trend line. */
export const TREND_EMPTY_ART = trendEmpty;
/** No goal defined: bars and a target. */
export const GOAL_ART = goal;

export function artForPath(_pathname: string): PageArt {
  return DASHBOARD_ART;
}
