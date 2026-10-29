import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import FormDialog from "../components/FormDialog";
import reportArt from "../assets/scheduled-report.svg";
import MarkdownMessage from "../components/MarkdownMessage";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import { FilterSelect, useFilterBar } from "@cbi/web-shared/components/FilterBar";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { chart } from "@cbi/web-shared/theme";

type ReportInput = { name: string; instructions: string; enabled: boolean; schedule_mode: "interval" | "fixed"; interval_hours: number | null; fixed_hours: number[]; max_retries: number; retry_base_minutes: number };
type Report = ReportInput & { id: string; next_run_at: string | null; archived_at: string | null };
type Run = { id: string; report_id: string; name: string; instructions: string; trigger: string; status: string; from_date: string; to_date: string; timezone: string; content: string | null; error_detail: string | null; created_at: string; sources: {call_id: string}[]; model: string | null; attempt_count: number; max_retries: number; next_attempt_at: string | null; coverage: Record<string, unknown> };
type RunSummary = Pick<Run, "id" | "report_id" | "name" | "trigger" | "status" | "from_date" | "to_date" | "created_at" | "error_detail" | "attempt_count" | "max_retries" | "next_attempt_at" | "coverage">;
const empty: ReportInput = { name: "", instructions: "", enabled: true, schedule_mode: "interval", interval_hours: 24, fixed_hours: [], max_retries: 3, retry_base_minutes: 5 };
const statuses: Record<string, string> = { queued: "در صف", running: "در حال ساخت", succeeded: "آماده", failed: "ناموفق" };
const STATUS_COLORS: Record<string, string> = { queued: chart.warning, running: chart.cyan, succeeded: chart.primary, failed: chart.danger };
const PAGE_SIZE = 25;
const RUN_COLUMNS: SkeletonColumn[] = [
  { label: "گزارش", width: "10rem" },
  { label: "زمان", width: "8.5rem" },
  { label: "روش اجرا", kind: "badge" },
  { label: "تلاش", width: "3rem" },
  { label: "وضعیت", kind: "badge" },
];

function runStatusLabel(run: { status: string; next_attempt_at: string | null }) {
  return run.status === "queued" && run.next_attempt_at ? "در انتظار تلاش مجدد" : statuses[run.status] ?? run.status;
}

/** Square tag with a status dot, in the chart palette. */
function RunStatusBadge({ run }: { run: { status: string; next_attempt_at: string | null } }) {
  const color = STATUS_COLORS[run.status] ?? chart.neutral;
  return <span className="badge border bg-[#F2F0EF] font-semibold" style={{ borderColor: color, color }}><i className="inline-block h-1.5 w-1.5" style={{ background: color }} aria-hidden="true" />{runStatusLabel(run)}</span>;
}

function TriggerBadge({ trigger }: { trigger: string }) {
  return <span className="badge border border-[#B2AC88] bg-[#F2F0EF] text-slate-600">{trigger === "manual" ? "اجرای دستی" : "زمان‌بندی‌شده"}</span>;
}

export default function ScheduledReports() {
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
  const [detail, setDetail] = useState<Run | null>(null);
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
    // Skeleton only when the list changes; opening a run just loads its detail.
    const listKey = [settings, archived, offset, reportId, status, trigger, revision].join("|");
    if (listKeyRef.current !== listKey) { listKeyRef.current = listKey; setLoading(true); }
    const query = new URLSearchParams({ offset: String(offset), limit: "25" });
    if (reportId) query.set("report_id", reportId);
    if (status) query.set("status", status);
    if (trigger) query.set("trigger", trigger);
    async function load() {
      const sequence = ++requestSequence.current;
      try {
        const [definitions, archive, run] = await Promise.all([
          settings ? request<Report[]>(`/v1/scheduled-reports?archived=${archived}`) : Promise.all([
            request<Report[]>("/v1/scheduled-reports"), request<Report[]>("/v1/scheduled-reports?archived=true"),
          ]).then(([active, previous]) => [...active, ...previous]),
          request<{items: RunSummary[]; total: number}>(`/v1/scheduled-reports/runs?${query}`),
          selected ? request<Run>(`/v1/scheduled-reports/runs/${selected}`) : Promise.resolve(null),
        ]);
        if (active && sequence === requestSequence.current) { setReports(definitions); setRuns(archive.items); setTotal(archive.total); setDetail(run); setError(""); setLoading(false); }
      } catch (err) { if (active && sequence === requestSequence.current) { setError((err as Error).message); setLoading(false); } }
      finally { if (active) timer = window.setTimeout(() => void load(), 10000); }
    }
    void load();
    return () => { active = false; requestSequence.current += 1; window.clearTimeout(timer); };
  }, [settings, archived, offset, reportId, status, trigger, selected, revision]);
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
  const tabClass = (active: boolean) => `h-9 whitespace-nowrap px-4 text-sm ${active ? "bg-[#4B6E48] text-white" : "text-slate-600 hover:bg-[#F2F0EF]"}`;
  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex border border-[#B2AC88] bg-white p-0.5" role="group" aria-label="بخش گزارش‌ها">
        <button type="button" aria-pressed={!settings} className={tabClass(!settings)} onClick={() => change({tab: "archive"})}>آرشیو گزارش‌ها</button>
        <button type="button" aria-pressed={settings} className={tabClass(settings)} onClick={() => change({tab: "settings", run: null})}>مدیریت و زمان‌بندی</button>
      </div>
      <button type="button" className="btn-ghost flex h-10 w-10 items-center justify-center !p-0" onClick={refresh} aria-label="به‌روزرسانی" title="به‌روزرسانی">
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14-4.5L4 9" /><path d="M4 4v5h5" /><path d="M4 13a8 8 0 0 0 14 4.5L20 15" /><path d="M20 20v-5h-5" /></svg>
      </button>
      {!settings ? filterBar.toolbar : null}
    </div>
  );
  const scheduleText = (report: Report) => report.schedule_mode === "interval" ? `هر ${fmt.int(report.interval_hours || 0)} ساعت` : `ساعت‌های ${report.fixed_hours.map(hour => `${fmt.int(hour)}:۰۰`).join("، ")}`;
  return <div className="space-y-5" dir="rtl">
    <PageHeader title="گزارش‌های زمان‌بندی‌شده" description="گزارش‌های مدیریتی با معیارهای دلخواه، بر پایهٔ اطلاعات و حافظهٔ سازمان" actions={toolbar} />
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
          {!report.archived_at ? <button className="btn h-9 px-3 py-0 text-xs" disabled={busy} onClick={() => void mutate(async () => { const run = await request<Run>(`/v1/scheduled-reports/${report.id}/run`, {method: "POST", body: {idempotency_key: crypto.randomUUID()}}); change({tab: "archive", run: run.id, status: null, offset: null}); })}>اجرای همین حالا</button> : null}
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
      {detail && detail.id === selected ? <article className="card">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="font-bold">{detail.name}</h2><p className="mt-1 text-xs text-slate-500">{fmt.dateTime(detail.from_date)} تا {fmt.dateTime(detail.to_date)} · {detail.timezone}</p></div>
          <button type="button" className="btn-ghost h-9 px-3 py-0 text-xs" onClick={() => change({run: null})}>بستن گزارش</button>
        </div>
        <div className="mb-4 flex flex-wrap items-center gap-2"><RunStatusBadge run={detail} /><TriggerBadge trigger={detail.trigger} /><span className="badge border border-[#B2AC88] bg-[#F2F0EF] text-slate-600">تلاش {fmt.int(detail.attempt_count)} از {fmt.int(detail.max_retries + 1)}</span>{detail.next_attempt_at ? <span className="text-xs text-slate-500">تلاش بعدی: {fmt.dateTime(detail.next_attempt_at)}</span> : null}</div>
        {detail.error_detail ? <p className="mb-4 border border-[#B2AC88] border-s-4 bg-[#F2F0EF] p-3 text-sm text-slate-700" style={{ borderInlineStartColor: chart.warning }}>{detail.error_detail}</p> : null}
        <div className="mb-4 grid gap-3 sm:grid-cols-3">{([["تماس‌ها", detail.coverage.calls], ["تماس‌های ایندکس‌شده", detail.coverage.indexed_calls], ["شواهد معنایی", detail.coverage.semantic_results]] as Array<[string, unknown]>).map(([label, value]) => <div key={String(label)} className="border border-[#B2AC88] bg-[#F2F0EF] p-3"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-xl font-bold text-[#4B6E48]">{fmt.int(Number(value || 0))}</div></div>)}</div>
        {Array.isArray(detail.coverage.warnings) && detail.coverage.warnings.length ? <ul className="mb-4 list-inside list-disc text-sm text-slate-600">{detail.coverage.warnings.map((warning, index) => <li key={index}>{String(warning)}</li>)}</ul> : null}
        {detail.content ? <MarkdownMessage content={detail.content}/> : detail.status === "failed" ? null : <p role="status" className="text-sm text-slate-500">{detail.error_detail || "گزارش در حال آماده‌سازی است…"}</p>}
        <details className="mt-4 border-t border-[#B2AC88] pt-3"><summary className="cursor-pointer text-sm text-[#4B6E48]">معیارهای این اجرا</summary><p className="mt-2 whitespace-pre-wrap text-sm text-slate-600">{detail.instructions}</p></details>
        {detail.sources.length ? <div className="mt-4 flex flex-wrap gap-2">{detail.sources.map(source => <Link className="btn-ghost h-9 px-3 py-0 text-xs inline-flex items-center" key={source.call_id} to={`/calls/${source.call_id}`}>مشاهده تماس {source.call_id.slice(0, 8)}</Link>)}</div> : null}
      </article> : null}
      <div className="card">
        {loading ? <SkeletonTable columns={RUN_COLUMNS} rows={runs.length ? Math.min(runs.length, PAGE_SIZE) : 6} /> : runs.length === 0 ? <Empty>گزارشی در این فیلتر وجود ندارد.</Empty> : <table className="table" dir="rtl">
          <thead><tr>{RUN_COLUMNS.map((column, index) => <th key={index}>{column.label}</th>)}</tr></thead>
          <tbody>{runs.map(run => <tr key={run.id} className={`table-row-link ${run.id === selected ? "font-bold" : ""}`} role="link" tabIndex={0} aria-current={run.id === selected} onClick={() => change({run: run.id})} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); change({run: run.id}); } }}>
            <td>{run.name}</td>
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
