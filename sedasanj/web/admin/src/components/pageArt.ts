import office from "../assets/manager-office-line-art.webp";
import emptyState from "../assets/empty-state.svg";

export const EMPTY_STATE_ART = emptyState;

export function artForPath(_pathname: string): string {
  return office;
}
