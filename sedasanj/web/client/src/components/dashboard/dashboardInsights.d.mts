import type { KpiDashboard } from "../../types";

export type Cards = KpiDashboard["cards"];
export type DashboardAction = KpiDashboard["actions"][number];

export interface Signal {
  key: "wins" | "revenue" | "conversion" | "answer_rate" | "satisfaction" | "quality" | "follow_up";
  unit: "percent" | "points";
  change: number;
  significant: boolean;
  weight: number;
}

export interface ActionGroup {
  type: string;
  severity: string;
  count: number;
  items: DashboardAction[];
}

export type SummaryTone = "good" | "bad" | "mixed" | "steady" | "unknown";

export function relativeChange(current: number | null | undefined, previous: number | null | undefined): number | null;
export function buildSignals(cards: Cards, options?: { operator?: boolean }): Signal[];
export function groupActions(actions: DashboardAction[]): ActionGroup[];
export function summarize(
  cards: Cards,
  actions: DashboardAction[],
  options?: { operator?: boolean },
): { tone: SummaryTone; headline: string; detail: string | null; signals: Signal[] };
