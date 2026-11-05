import { fmt } from "../api";
import { chart } from "@cbi/web-shared/theme";
import { AssistantCharts } from "./AssistantCharts";
import DocumentActions from "./DocumentActions";
import MarkdownMessage from "./MarkdownMessage";
import type { Run } from "../lib/scheduledReports";

export const statuses: Record<string, string> = { queued: "در صف", running: "در حال ساخت", succeeded: "آماده", failed: "ناموفق" };
const STATUS_COLORS: Record<string, string> = { queued: chart.warning, running: chart.cyan, succeeded: chart.primary, failed: chart.danger };
function runStatusLabel(run: { status: string; next_attempt_at: string | null }) {
  return run.status === "queued" && run.next_attempt_at ? "در انتظار تلاش مجدد" : statuses[run.status] ?? run.status;
}

/** Square tag with a status dot, in the chart palette. */
export function RunStatusBadge({ run }: { run: { status: string; next_attempt_at: string | null } }) {
  const color = STATUS_COLORS[run.status] ?? chart.neutral;
  return <span className="badge border bg-[#F2F0EF] font-semibold" style={{ borderColor: color, color }}><i className="inline-block h-1.5 w-1.5" style={{ background: color }} aria-hidden="true" />{runStatusLabel(run)}</span>;
}

export function TriggerBadge({ trigger }: { trigger: string }) {
  return <span className="badge border border-[#B2AC88] bg-[#F2F0EF] text-slate-600">{trigger === "manual" ? "اجرای دستی" : "زمان‌بندی‌شده"}</span>;
}

export function reportPeriod(run: Run) {
  const format = (timeZone: string) => new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
    dateStyle: "short", timeStyle: "short", timeZone,
  });
  let timezone = run.timezone;
  let formatter: Intl.DateTimeFormat;
  try {
    formatter = format(timezone);
  } catch {
    timezone = "Asia/Tehran";
    formatter = format(timezone);
  }
  return { timezone, window: `${formatter.format(new Date(run.from_date))} تا ${formatter.format(new Date(run.to_date))}` };
}

export function ReportCoverage({ coverage }: { coverage: Record<string, unknown> }) {
  return <>
    <div className="mb-4 grid gap-3 sm:grid-cols-3">{([["تماس‌ها", coverage.calls], ["تماس‌های ایندکس‌شده", coverage.indexed_calls], ["شواهد معنایی", coverage.semantic_results]] as Array<[string, unknown]>).map(([label, value]) => <div key={String(label)} className="border border-[#B2AC88] bg-[#F2F0EF] p-3"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-xl font-bold text-[#4B6E48]">{fmt.int(Number(value || 0))}</div></div>)}</div>
        {Array.isArray(coverage.warnings) && coverage.warnings.length ? <ul className="mb-4 list-inside list-disc text-sm text-slate-600">{coverage.warnings.map((warning, index) => <li key={index}>{String(warning)}</li>)}</ul> : null}
  </>;
}

export function ReportDocumentActions({ run, content, period }: { run: Run; content: string; period: ReturnType<typeof reportPeriod> }) {
  const metadata: Array<[string, string]> = [["بازه گزارش", period.window]];
  if (run.title && run.title !== run.name) metadata.push(["نام زمان‌بندی", run.name]);
  metadata.push(["منطقه زمانی", period.timezone]);
  return (
    <DocumentActions iconOnly contentKey={run.id + content + JSON.stringify([run.charts, run.coverage, metadata])} title={run.title || run.name} kind="گزارش زمان‌بندی‌شده" metadata={metadata}>
      <MarkdownMessage content={content} />
      <AssistantCharts charts={run.charts ?? []} print />
    </DocumentActions>
  );
}
