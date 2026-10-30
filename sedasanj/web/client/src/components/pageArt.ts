import office from "../assets/manager-office-line-art.webp";
import emptyState from "../assets/empty-state.webp";

export type PageArt = { src: string; fit: "illustration" | "backdrop" };

const DASHBOARD_ART: PageArt = { src: office, fit: "backdrop" };

export const EMPTY_STATE_ART = emptyState;

export function artForPath(_pathname: string): PageArt {
  return DASHBOARD_ART;
}
