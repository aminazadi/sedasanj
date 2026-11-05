export type ReportTab = "report" | "sources" | "criteria";
export const REPORT_TABS: ReportTab[];
export function reportTabFromSearch(params: URLSearchParams): ReportTab;
export function reportArchiveUrl(params: URLSearchParams): string;
export function reportDetailUrl(runId: string, params: URLSearchParams): string;
