export const REPORT_TABS = ["report", "sources", "criteria"];

export function reportTabFromSearch(params) {
  const value = params.get("detail_tab");
  return REPORT_TABS.includes(value) ? value : "report";
}

export function reportArchiveUrl(params) {
  const query = new URLSearchParams(params);
  query.delete("run");
  query.delete("detail_tab");
  query.set("tab", "archive");
  return `/scheduled-reports?${query}`;
}

export function reportDetailUrl(runId, params) {
  const query = new URLSearchParams(params);
  query.delete("run");
  query.delete("detail_tab");
  return `/scheduled-reports/runs/${encodeURIComponent(runId)}${query.size ? `?${query}` : ""}`;
}
