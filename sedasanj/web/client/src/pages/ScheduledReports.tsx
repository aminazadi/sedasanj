import { useTablePageSize } from "../lib/useTablePagination";
import { useEffect, useRef, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import DocumentTabs from "../components/DocumentTabs";
import FormDialog from "../components/FormDialog";
import reportArt from "../assets/scheduled-report.webp";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import { FilterSelect, useFilterBar } from "@cbi/web-shared/components/FilterBar";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";

import type { ReportInput, Report, Run, RunSummary } from "../lib/scheduledReports";
import { RunStatusBadge, TriggerBadge, statuses } from "../components/ScheduledReportDocument";
import { reportDetailUrl } from "../lib/scheduledReportNavigation.mjs";

const empty: ReportInput = { name: "", instructions: "", enabled: true, schedule_mode: "interval", interval_hours: 24, fixed_hours: [], max_retries: 3, retry_base_minutes: 5 };
const RUN_COLUMNS: SkeletonColumn[] = [
  { label: "گزارش", width: "10rem" },
  { label: "زمان", width: "8.5rem" },
  { label: "روش اجرا", kind: "badge" },
  { label: "تلاش", width: "3rem" },
  { label: "وضعیت", kind: "badge" },
];

export default function ScheduledReports() {
  const navigate = useNavigate();
  const [PAGE_SIZE] = useTablePageSize();
  const [params, setParams] = useSearchParams();
  const settings = params.get("tab") === "settings";
  const archived = params.get("archived") === "true";
  const selected = params.get("run");
  const reportId = params.get("report") || "";
  const status = params.get("status") || "";
  const trigger = params.get("trigger") || "";
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const [reports, setReports] = useState<Report[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [form, setForm] = useState<ReportInput>({ ...empty });
  const [editing, setEditing] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const requestSequence = useRef(0);
  const listKeyRef = useRef("");
  const refresh = () => setRevision(value => value + 1);
  function change(values: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) { if (value) next.set(key, value); else next.delete(key); }
    setParams(next);
  }
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const listKey = [PAGE_SIZE, settings, archived, offset, reportId, status, trigger, revision].join("|");
    if (listKeyRef.current !== listKey) { listKeyRef.current = listKey; setLoading(true); }
    const query = new URLSearchParams({ offset: String(offset), limit: String(PAGE_SIZE) });
    if (reportId) query.set("report_id", reportId);
    if (status) query.set("status", status);
    if (trigger) query.set("trigger", trigger);
    async function load() {
      const sequence = ++requestSequence.current;
      try {
        const [definitions, archive] = await Promise.all([
          settings ? request<Report[]>(`/v1/scheduled-reports?archived=${archived}`) : Promise.all([
            request<Report[]>("/v1/scheduled-reports"), request<Report[]>("/v1/scheduled-reports?archived=true"),
          ]).then(([active, previous]) => [...active, ...previous]),
          request<{items: RunSummary[]; total: number}>(`/v1/scheduled-reports/runs?${query}`),
        ]);
        if (active && sequence === requestSequence.current) { setReports(definitions); setRuns(archive.items); setTotal(archive.total); setError(""); setLoading(false); }
      } catch (err) { if (active && sequence === requestSequence.current) { setError((err as Error).message); setLoading(false); } }
      finally { if (active) timer = window.setTimeout(() => void load(), 10000); }
    }
    if (!selected) void load();
    return () => { active = false; requestSequence.current += 1; window.clearTimeout(timer); };
  }, [PAGE_SIZE, settings, archived, offset, reportId, status, trigger, selected, revision]);
  async function mutate(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); refresh(); } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  function edit(report: Report) {
    setEditing(report.id);
    setForm({name: report.name, instructions: report.instructions, enabled: report.enabled, schedule_mode: report.schedule_mode, interval_hours: report.interval_hours, fixed_hours: report.fixed_hours, max_retries: report.max_retries, retry_base_minutes: report.retry_base_minutes});
    change({tab: "settings"});
    setDialogOpen(true);
  }
  function closeDialog() { setDialogOpen(false); setEditing(null); setForm({...empty}); setError(""); }
  function openNew() { setEditing(null); setForm({...empty}); setDialogOpen(true); }
  const reportOptions = reports.map(report => ({ value: report.id, label: report.name }));
  const filterBar = useFilterBar({
    hasActive: Boolean(reportId || status || trigger),
    onClear: () => change({ report: null, status: null, trigger: null, offset: null }),
    fields: [
      { id: "report", label: "گزارش", active: Boolean(reportId), onRemove: () => change({ report: null, offset: null }), control: <FilterSelect value={reportId} onChange={value => change({ report: value, offset: null })} options={reportOptions} allLabel="همه گزارش‌ها" /> },
      { id: "status", label: "وضعیت", active: Boolean(status), onRemove: () => change({ status: null, offset: null }), control: <FilterSelect value={status} onChange={value => change({ status: value, offset: null })} options={Object.entries(statuses).map(([value, label]) => ({ value, label }))} allLabel="همه وضعیت‌ها" /> },
      { id: "trigger", label: "روش اجرا", active: Boolean(trigger), onRemove: () => change({ trigger: null, offset: null }), control: <FilterSelect value={trigger} onChange={value => change({ trigger: value, offset: null })} options={[{ value: "scheduled", label: "زمان‌بندی‌شده" }, { value: "manual", label: "دستی" }]} allLabel="همه اجراها" /> },
    ],
  });
  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className="btn-ghost flex h-10 w-10 items-center justify-center !p-0" onClick={refresh} aria-label="به‌روزرسانی" title="به‌روزرسانی">
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14-4.5L4 9" /><path d="M4 4v5h5" /><path d="M4 13a8 8 0 0 0 14 4.5L20 15" /><path d="M20 20v-5h-5" /></svg>
      </button>
      {!settings ? filterBar.toolbar : null}
    </div>
  );
  const scheduleText = (report: Report) => report.schedule_mode === "interval" ? `هر ${fmt.int(report.interval_hours || 0)} ساعت` : `ساعت‌های ${report.fixed_hours.map(hour => `${fmt.int(hour)}:۰۰`).join("، ")}`;
  if (selected) return <Navigate to={reportDetailUrl(selected, params)} replace />;
  return <div className="space-y-5" dir="rtl">
    <PageHeader title="گزارش‌های زمان‌بندی‌شده" description="گزارش‌های مدیریتی با معیارهای دلخواه، بر پایهٔ اطلاعات و حافظهٔ سازمان" actions={toolbar} />
    <DocumentTabs align="start" value={settings ? "settings" : "archive"} options={[{ value: "archive", label: "آرشیو گزارش‌ها" }, { value: "settings", label: "مدیریت و زمان‌بندی" }]} onChange={value => change({ tab: value, ...(value === "settings" ? { run: null } : {}) })} label="بخش گزارش‌ها" />
    <ErrorBox message={error || null} />
    {settings ? <>
      <FormDialog
        open={dialogOpen}
        title={editing ? "ویرایش گزارش" : "گزارش جدید"}
        description="نام، معیارها و زمان‌بندی اجرا را مشخص کنید."
        art={reportArt}
        wide
        submitLabel="ذخیره گزارش"
        busy={busy}
        error={error || null}
        submitDisabled={form.schedule_mode === "fixed" && !form.fixed_hours.length}
        onClose={closeDialog}
        onSubmit={() => void mutate(async () => { await request(`/v1/scheduled-reports${editing ? `/${editing}` : ""}`, {method: editing ? "PUT" : "POST", body: form}); closeDialog(); })}
      >
        <label><span>نام گزارش</span><input required maxLength={200} value={form.name} onChange={event => setForm({...form, name: event.target.value})} autoFocus /></label>
        <label><span>معیارها و دستور گزارش</span><textarea rows={6} required minLength={2} maxLength={12000} value={form.instructions} onChange={event => setForm({...form, instructions: event.target.value})} placeholder="مثلاً دلایل نارضایتی مشتریان، کیفیت پاسخ‌گویی و اقدام‌های لازم را با شواهد تماس بررسی کن."/></label>
        <p>نوع نمودار را هم می‌توانید در معیارها بنویسید. برای نمونه، «روند روزانه تماس‌ها را با نمودار خطی نمایش بده».</p>
        <label><span>روش زمان‌بندی</span><select value={form.schedule_mode} onChange={event => setForm({...form, schedule_mode: event.target.value as ReportInput["schedule_mode"], interval_hours: event.target.value === "interval" ? 24 : null, fixed_hours: event.target.value === "fixed" ? [9] : []})}><option value="interval">هر چند ساعت از زمان فعال‌سازی</option><option value="fixed">ساعت‌های ثابت در منطقهٔ زمانی سازمان</option></select></label>
        {form.schedule_mode === "interval"
          ? <label><span>فاصلهٔ اجرا (ساعت)</span><input type="number" min={1} max={8760} required value={form.interval_hours ?? 24} onChange={event => setForm({...form, interval_hours: Number(event.target.value)})}/></label>
          : <fieldset className="demo-field"><legend>ساعت‌های اجرا</legend><div className="mt-2 grid grid-cols-4 gap-2 sm:grid-cols-6">{Array.from({length: 24}, (_, hour) => { const on = form.fixed_hours.includes(hour); return <button key={hour} type="button" aria-pressed={on} className={`h-10 border text-sm ${on ? "border-[#4B6E48] bg-[#4B6E48] text-white" : "border-[#cbd5e1] bg-[#f8fafc] text-slate-600 hover:bg-white"}`} onClick={() => setForm({...form, fixed_hours: on ? form.fixed_hours.filter(value => value !== hour) : [...form.fixed_hours, hour].sort((a, b) => a - b)})}>{fmt.int(hour)}:۰۰</button>; })}</div></fieldset>}
        <div className="grid gap-[18px] sm:grid-cols-2">
          <label><span>تعداد تلاش مجدد خودکار</span><input type="number" min={0} max={3} value={form.max_retries} onChange={event => setForm({...form, max_retries: Number(event.target.value)})}/></label>
          <label><span>فاصلهٔ پایهٔ تلاش مجدد (دقیقه)</span><input type="number" min={1} max={60} value={form.retry_base_minutes} onChange={event => setForm({...form, retry_base_minutes: Number(event.target.value)})}/></label>
        </div>
        <ToggleSwitch checked={form.enabled} onChange={enabled => setForm({...form, enabled})} label="زمان‌بندی فعال باشد" />
        <p>فاصلهٔ تلاش‌ها با ضریب سه افزایش می‌یابد. خطای سهمیه یا دسترسی دوباره اجرا نمی‌شود. هر گزارش از اجرای زمان‌بندی‌شدهٔ قبلی تا زمان اجرا را بررسی می‌کند؛ اجرای دستی، زمان‌بندی را جابه‌جا نمی‌کند و تولید موفق گزارش از سهمیهٔ دستیار سازمان استفاده می‌کند.</p>
      </FormDialog>
      <section className="grid items-center gap-6 border border-[#B2AC88] px-6 py-6 sm:grid-cols-[minmax(0,1fr)_auto]" style={{ background: "#f2f0ef radial-gradient(circle, rgb(137 137 137 / 0.14) 0 1px, transparent 1.15px) 0 0 / 7px 7px" }}>
        <div className="min-w-0 max-w-xl">
          <h2 className="text-base font-bold text-[#4B6E48]">ساخت گزارش جدید</h2>
          <p className="mt-2 text-sm leading-7 text-slate-500">معیارهای گزارش را بنویسید و زمان اجرای خودکار را تعیین کنید؛ نتیجهٔ هر اجرا در آرشیو گزارش‌ها نگهداری می‌شود.</p>
          <button type="button" className="btn mt-4 inline-flex min-h-[42px] items-center gap-2 px-5" onClick={openNew}>
            <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            گزارش جدید
          </button>
        </div>
        <img className="hidden h-36 w-auto max-w-full mix-blend-multiply sm:block" src={reportArt} alt="" aria-hidden="true" />
      </section>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-sm text-slate-500">{loading && !reports.length ? "…" : `${fmt.int(reports.length)} تعریف`}</span>
        <ToggleSwitch checked={archived} onChange={value => change({archived: value ? "true" : null})} label="آرشیوشده‌ها" />
      </div>
      {loading && !reports.length ? <SkeletonTable columns={[{ label: "گزارش", width: "10rem" }, { label: "زمان‌بندی", width: "8rem" }, { label: "اجرای بعدی", width: "8.5rem" }, { label: "وضعیت", kind: "badge" }]} rows={3} /> : reports.length ? <div className="grid gap-4 lg:grid-cols-2">{reports.map(report => <section className="card flex flex-col" key={report.id}>
        <div className="mb-3 flex items-start justify-between gap-3"><h3 className="font-bold">{report.name}</h3><span className="badge border border-[#B2AC88] bg-[#F2F0EF] text-slate-600">{report.archived_at ? "آرشیوشده" : report.enabled ? "فعال" : "متوقف"}</span></div>
        <p className="line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{report.instructions}</p>
        <dl className="mt-3 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
          <div className="flex justify-between gap-2"><dt className="text-slate-500">زمان‌بندی</dt><dd>{scheduleText(report)}</dd></div>
          <div className="flex justify-between gap-2"><dt className="text-slate-500">اجرای بعدی</dt><dd>{report.next_run_at ? fmt.dateTime(report.next_run_at) : "—"}</dd></div>
          <div className="flex justify-between gap-2"><dt className="text-slate-500">تلاش مجدد</dt><dd>{fmt.int(report.max_retries)} بار</dd></div>
          <div className="flex justify-between gap-2"><dt className="text-slate-500">فاصلهٔ پایه</dt><dd>{fmt.int(report.retry_base_minutes)} دقیقه</dd></div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-2 border-t border-[#B2AC88] pt-3">
          {!report.archived_at ? <button className="btn h-9 px-3 py-0 text-xs" disabled={busy} onClick={() => void mutate(async () => { const run = await request<Run>(`/v1/scheduled-reports/${report.id}/run`, {method: "POST", body: {idempotency_key: crypto.randomUUID()}}); navigate(reportDetailUrl(run.id, params)); })}>اجرای همین حالا</button> : null}
          <button className="btn-ghost h-9 px-3 py-0 text-xs" onClick={() => change({tab: "archive", report: report.id, offset: null, run: null})}>مشاهده آرشیو</button>
          {!report.archived_at ? <>
            <button className="btn-ghost h-9 px-3 py-0 text-xs" onClick={() => edit(report)}>ویرایش</button>
            <button className="btn-ghost h-9 px-3 py-0 text-xs" disabled={busy} onClick={() => void mutate(() => request(`/v1/scheduled-reports/${report.id}`, {method: "PUT", body: {name: report.name, instructions: report.instructions, schedule_mode: report.schedule_mode, interval_hours: report.interval_hours, fixed_hours: report.fixed_hours, max_retries: report.max_retries, retry_base_minutes: report.retry_base_minutes, enabled: !report.enabled}}))}>{report.enabled ? "توقف" : "فعال‌سازی"}</button>
            <button className="btn-ghost h-9 px-3 py-0 text-xs" disabled={busy} onClick={() => void mutate(() => request(`/v1/scheduled-reports/${report.id}`, {method: "DELETE"}))}>آرشیو تعریف</button>
          </> : null}
        </div>
      </section>)}</div> : null}
      {!reports.length && !loading ? <div className="card"><Empty>گزارشی تعریف نشده است.</Empty></div> : null}
    </> : <>
      {filterBar.fields}
      <div className="card">
        {loading ? <SkeletonTable columns={RUN_COLUMNS} rows={runs.length ? Math.min(runs.length, PAGE_SIZE) : 6} /> : runs.length === 0 ? <Empty>گزارشی در این فیلتر وجود ندارد.</Empty> : <table className="table" dir="rtl">
          <thead><tr>{RUN_COLUMNS.map((column, index) => <th key={index}>{column.label}</th>)}</tr></thead>
          <tbody>{runs.map(run => <tr key={run.id} className="table-row-link" role="link" tabIndex={0} onClick={() => navigate(reportDetailUrl(run.id, params))} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); navigate(reportDetailUrl(run.id, params)); } }}>
            <td>{run.title || run.name}</td>
            <td>{fmt.dateTime(run.created_at)}</td>
            <td><TriggerBadge trigger={run.trigger} /></td>
            <td>{fmt.int(run.attempt_count)} از {fmt.int(run.max_retries + 1)}{run.next_attempt_at ? <small className="block text-xs text-slate-500">بعدی: {fmt.dateTime(run.next_attempt_at)}</small> : null}</td>
            <td><RunStatusBadge run={run} /></td>
          </tr>)}</tbody>
        </table>}
        <Pagination page={Math.floor(offset / PAGE_SIZE) + 1} hasPrevious={offset > 0} hasNext={offset + PAGE_SIZE < total} total={total} loading={loading} onPrevious={() => change({offset: String(Math.max(0, offset - PAGE_SIZE))})} onNext={() => change({offset: String(offset + PAGE_SIZE)})} />
      </div>
    </>}
  </div>;
}
