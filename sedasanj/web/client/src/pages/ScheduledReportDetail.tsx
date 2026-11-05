import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { fmt, request } from "../api";
import { AssistantCharts } from "../components/AssistantCharts";
import DocumentActionIcon, { DOCUMENT_ACTION_CLASS } from "../components/DocumentActionIcon";
import DocumentEditor from "../components/DocumentEditor";
import DocumentHeader from "../components/DocumentHeader";
import DocumentTabs from "../components/DocumentTabs";
import MarkdownMessage from "../components/MarkdownMessage";
import { ReportCoverage, ReportDocumentActions, RunStatusBadge, TriggerBadge, reportPeriod } from "../components/ScheduledReportDocument";
import { Empty, ErrorBox, Loading } from "../components/Widgets";
import { REPORT_TABS, reportArchiveUrl, reportTabFromSearch, type ReportTab } from "../lib/scheduledReportNavigation.mjs";
import type { Run } from "../lib/scheduledReports";

const TAB_LABELS: Record<ReportTab, string> = { report: "گزارش", sources: "منابع و پوشش", criteria: "معیارهای گزارش" };

export default function ScheduledReportDetail() {
  const { runId } = useParams<{ runId: string }>();
  const [params, setParams] = useSearchParams();
  const tab = reportTabFromSearch(params);
  const report = useResource<Run>((signal) => request<Run>(`/v1/scheduled-reports/runs/${runId}`, { signal }), [runId]);
  const detail = report.data?.id === runId ? report.data : undefined;
  const [draft, setDraft] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editorReady, setEditorReady] = useState(tab === "report");
  useEffect(() => { setDraft(null); setNotice(null); setEditorReady(tab === "report"); }, [runId]);
  useEffect(() => { if (tab === "report") setEditorReady(true); }, [tab]);
  const active = detail?.status === "queued" || detail?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => report.reload({ silent: true }), 10000);
    return () => window.clearInterval(timer);
  }, [active, report.reload]);

  function selectTab(value: ReportTab) {
    const next = new URLSearchParams(params);
    next.set("detail_tab", value);
    setParams(next, { replace: true });
  }

  const back = <Link className={DOCUMENT_ACTION_CLASS} to={reportArchiveUrl(params)} aria-label="بازگشت به گزارش‌ها" title="بازگشت به گزارش‌ها"><DocumentActionIcon name="back" /></Link>;
  if (!detail && !report.error) return <Loading />;
  if (!detail) return <div className="space-y-4"><ErrorBox message={report.error} />{back}</div>;
  const period = reportPeriod(detail);
  return <div className="space-y-4" dir="rtl">
    <DocumentHeader title={detail.title || detail.name} status={<RunStatusBadge run={detail} />}
      metadata={<><span>{period.window}</span>{detail.title && detail.title !== detail.name ? <span>نام زمان‌بندی: {detail.name}</span> : null}</>}
      actions={<>{back}{detail.status === "succeeded" && detail.content ? <ReportDocumentActions run={detail} content={draft ?? detail.content} period={period} /> : null}</>}
    />
    {notice ? <div className="border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700" role="status">{notice}</div> : null}
    <ErrorBox message={report.error} />
    {detail.status !== "succeeded" ? <section className="card space-y-3" aria-label="وضعیت ساخت گزارش">
      <div className="flex flex-wrap items-center gap-2"><TriggerBadge trigger={detail.trigger} /><span className="text-sm">تلاش {fmt.int(detail.attempt_count)} از {fmt.int(detail.max_retries + 1)}</span>{detail.next_attempt_at ? <span className="text-sm">تلاش بعدی: {fmt.dateTime(detail.next_attempt_at)}</span> : null}</div>
      {detail.error_detail ? <p className="text-sm text-slate-700">{detail.error_detail}</p> : null}
      <p className="text-sm text-slate-500" role="status">{active ? "گزارش در حال آماده‌سازی است؛ نتیجه به‌صورت خودکار نمایش داده می‌شود." : "ساخت گزارش ناموفق بود؛ از بخش مدیریت و زمان‌بندی، گزارش را دوباره اجرا کنید."}</p>
    </section> : null}
    <section className="card">
      <DocumentTabs align="start" value={tab} options={REPORT_TABS.map(value => ({ value, label: TAB_LABELS[value] }))} onChange={selectTab} label="بخش‌های گزارش" />
      <div hidden={tab !== "report"} role="tabpanel" aria-label="گزارش">
        {detail.content ? <div className="document-body">{detail.status === "succeeded" && editorReady ? <DocumentEditor
          key={detail.id} content={detail.content} expectedContent={detail.content}
          path={`/v1/scheduled-reports/runs/${detail.id}`} onDraftChange={setDraft}
          onSaved={() => { setNotice("گزارش ذخیره شد."); report.reload({ silent: true }); }}
        /> : <MarkdownMessage content={detail.content} />}</div> : <Empty>{active ? "متن گزارش پس از پایان پردازش اینجا نمایش داده می‌شود." : "متنی برای این گزارش ثبت نشده است."}</Empty>}
        <AssistantCharts charts={detail.charts ?? []} print />
      </div>
      {tab === "sources" ? <div role="tabpanel" aria-label="منابع و پوشش">
        <ReportCoverage coverage={detail.coverage} />
        {detail.sources.length ? <div className="flex flex-wrap gap-2">{detail.sources.map(source => <Link className="btn-ghost inline-flex h-9 items-center px-3 py-0 text-xs" key={source.call_id} to={`/calls/${source.call_id}`}>مشاهده تماس {source.call_id.slice(0, 8)}</Link>)}</div> : <Empty>تماسی به‌عنوان منبع این گزارش ثبت نشده است.</Empty>}
      </div> : null}
      {tab === "criteria" ? <div role="tabpanel" aria-label="معیارهای گزارش"><p className="whitespace-pre-wrap text-sm leading-8">{detail.instructions}</p><p className="mt-4 text-xs text-slate-500">منطقه زمانی: <bdi>{period.timezone}</bdi></p></div> : null}
    </section>
  </div>;
}
