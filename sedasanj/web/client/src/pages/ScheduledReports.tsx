import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import MarkdownMessage from "../components/MarkdownMessage";
import { PageHeader } from "../components/PageHeader";

type ReportInput = { name: string; instructions: string; enabled: boolean; schedule_mode: "interval" | "fixed"; interval_hours: number | null; fixed_hours: number[] };
type Report = ReportInput & { id: string; next_run_at: string | null; archived_at: string | null };
type Run = { id: string; report_id: string; name: string; instructions: string; trigger: string; status: string; from_date: string; to_date: string; timezone: string; content: string | null; error_detail: string | null; created_at: string; sources: {call_id: string}[]; model: string | null };
type RunSummary = Pick<Run, "id" | "report_id" | "name" | "trigger" | "status" | "from_date" | "to_date" | "created_at" | "error_detail">;
const empty: ReportInput = { name: "", instructions: "", enabled: true, schedule_mode: "interval", interval_hours: 24, fixed_hours: [] };
const statuses: Record<string, string> = { queued: "در صف", running: "در حال ساخت", succeeded: "آماده", failed: "ناموفق" };

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
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const refresh = () => setRevision(value => value + 1);
  function change(values: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(values)) { if (value) next.set(key, value); else next.delete(key); }
    setParams(next);
  }
  useEffect(() => {
    let active = true;
    const query = new URLSearchParams({ offset: String(offset), limit: "25" });
    if (reportId) query.set("report_id", reportId);
    if (status) query.set("status", status);
    if (trigger) query.set("trigger", trigger);
    async function load() {
      try {
        const [definitions, archive, run] = await Promise.all([
          settings ? request<Report[]>(`/v1/scheduled-reports?archived=${archived}`) : Promise.all([
            request<Report[]>("/v1/scheduled-reports"), request<Report[]>("/v1/scheduled-reports?archived=true"),
          ]).then(([active, previous]) => [...active, ...previous]),
          request<{items: RunSummary[]; total: number}>(`/v1/scheduled-reports/runs?${query}`),
          selected ? request<Run>(`/v1/scheduled-reports/runs/${selected}`) : Promise.resolve(null),
        ]);
        if (active) { setReports(definitions); setRuns(archive.items); setTotal(archive.total); setDetail(run); setLoading(false); }
      } catch (err) { if (active) { setError((err as Error).message); setLoading(false); } }
    }
    void load();
    const timer = window.setInterval(() => void load(), 10000);
    return () => { active = false; window.clearInterval(timer); };
  }, [settings, archived, offset, reportId, status, trigger, selected, revision]);
  async function mutate(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); refresh(); } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  function edit(report: Report) {
    setEditing(report.id);
    setForm({name: report.name, instructions: report.instructions, enabled: report.enabled, schedule_mode: report.schedule_mode, interval_hours: report.interval_hours, fixed_hours: report.fixed_hours});
    change({tab: "settings"});
  }
  return <div className="space-y-5" dir="rtl">
    <PageHeader title="گزارش‌های زمان‌بندی‌شده" description="گزارش‌های مدیریتی با معیارهای دلخواه، بر پایهٔ اطلاعات و حافظهٔ سازمان" />
    <nav className="flex flex-wrap gap-2" aria-label="بخش گزارش‌ها">
      <button className={`btn ${!settings ? "bg-[#4B6E48] text-white" : "bg-white text-[#4B6E48]"}`} onClick={() => change({tab: "archive"})}>آرشیو گزارش‌ها</button>
      <button className={`btn ${settings ? "bg-[#4B6E48] text-white" : "bg-white text-[#4B6E48]"}`} onClick={() => change({tab: "settings", run: null})}>مدیریت و زمان‌بندی</button>
      <button className="btn-ghost" onClick={refresh}>به‌روزرسانی</button>
    </nav>
    {error ? <div className="rounded border border-red-200 bg-red-50 p-3 text-red-700" role="alert">{error}</div> : null}
    {loading ? <p role="status">در حال بارگذاری…</p> : null}
    {settings ? <>
      <section className="card space-y-4">
        <div className="flex items-center justify-between"><h2 className="font-bold">{editing ? "ویرایش گزارش" : "گزارش جدید"}</h2>{editing ? <button className="btn-ghost" onClick={() => { setEditing(null); setForm({...empty}); }}>گزارش جدید</button> : null}</div>
        <form className="space-y-4" onSubmit={event => { event.preventDefault(); void mutate(async () => { await request(`/v1/scheduled-reports${editing ? `/${editing}` : ""}`, {method: editing ? "PUT" : "POST", body: form}); setEditing(null); setForm({...empty}); }); }}>
          <label className="block space-y-1"><span>نام گزارش</span><input className="input" required maxLength={200} value={form.name} onChange={event => setForm({...form, name: event.target.value})}/></label>
          <label className="block space-y-1"><span>معیارها و دستور گزارش</span><textarea className="input min-h-40" required minLength={2} maxLength={12000} value={form.instructions} onChange={event => setForm({...form, instructions: event.target.value})} placeholder="مثلاً دلایل نارضایتی مشتریان، کیفیت پاسخ‌گویی و اقدام‌های لازم را با شواهد تماس بررسی کن."/></label>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block space-y-1"><span>روش زمان‌بندی</span><select className="input" value={form.schedule_mode} onChange={event => setForm({...form, schedule_mode: event.target.value as ReportInput["schedule_mode"], interval_hours: event.target.value === "interval" ? 24 : null, fixed_hours: event.target.value === "fixed" ? [9] : []})}><option value="interval">هر چند ساعت از زمان فعال‌سازی</option><option value="fixed">ساعت‌های ثابت در منطقهٔ زمانی سازمان</option></select></label>
            {form.schedule_mode === "interval" ? <label className="block space-y-1"><span>فاصلهٔ اجرا (ساعت)</span><input className="input" type="number" min={1} max={8760} required value={form.interval_hours ?? 24} onChange={event => setForm({...form, interval_hours: Number(event.target.value)})}/></label> : <fieldset><legend className="mb-2">ساعت‌های اجرا</legend><div className="flex flex-wrap gap-2">{Array.from({length: 24}, (_, hour) => <label key={hour} className="flex items-center gap-1 rounded border p-2 text-sm"><input type="checkbox" checked={form.fixed_hours.includes(hour)} onChange={event => setForm({...form, fixed_hours: event.target.checked ? [...form.fixed_hours, hour].sort((a,b) => a-b) : form.fixed_hours.filter(value => value !== hour)})}/>{fmt.int(hour)}:۰۰</label>)}</div></fieldset>}
          </div>
          <label className="flex items-center gap-2"><input type="checkbox" checked={form.enabled} onChange={event => setForm({...form, enabled: event.target.checked})}/>زمان‌بندی فعال باشد</label>
          <p className="text-sm text-slate-500">هر گزارش از اجرای زمان‌بندی‌شدهٔ قبلی تا زمان اجرا را بررسی می‌کند. اجرای دستی، زمان‌بندی را جابه‌جا نمی‌کند. تولید موفق گزارش از سهمیهٔ دستیار سازمان استفاده می‌کند.</p>
          <button className="btn" disabled={busy || (form.schedule_mode === "fixed" && !form.fixed_hours.length)}>{busy ? "در حال ذخیره…" : "ذخیره گزارش"}</button>
        </form>
      </section>
      <label className="flex gap-2"><input type="checkbox" checked={archived} onChange={event => change({archived: event.target.checked ? "true" : null})}/>نمایش تعریف‌های آرشیوشده</label>
      <div className="grid gap-4 lg:grid-cols-2">{reports.map(report => <section className="card space-y-3" key={report.id}>
        <div className="flex justify-between gap-3"><h3 className="font-bold">{report.name}</h3><span className="text-sm">{report.archived_at ? "آرشیوشده" : report.enabled ? "فعال" : "متوقف"}</span></div>
        <p className="whitespace-pre-wrap text-sm text-slate-600">{report.instructions}</p>
        <p className="text-sm">{report.schedule_mode === "interval" ? `هر ${fmt.int(report.interval_hours || 0)} ساعت` : `ساعت‌های ${report.fixed_hours.map(hour => `${fmt.int(hour)}:۰۰`).join("، ")}`}</p>
        <p className="text-sm">اجرای بعدی: {report.next_run_at ? fmt.dateTime(report.next_run_at) : "—"}</p>
        <div className="flex flex-wrap gap-2"><button className="btn-ghost" onClick={() => change({tab: "archive", report: report.id, offset: null, run: null})}>مشاهده آرشیو</button>{!report.archived_at ? <>
          <button className="btn" disabled={busy} onClick={() => void mutate(async () => { const run = await request<Run>(`/v1/scheduled-reports/${report.id}/run`, {method: "POST", body: {idempotency_key: crypto.randomUUID()}}); change({tab: "archive", run: run.id, status: null, offset: null}); })}>اجرای همین حالا</button>
          <button className="btn-ghost" onClick={() => edit(report)}>ویرایش</button>
          <button className="btn-ghost" disabled={busy} onClick={() => void mutate(() => request(`/v1/scheduled-reports/${report.id}`, {method: "PUT", body: {name: report.name, instructions: report.instructions, schedule_mode: report.schedule_mode, interval_hours: report.interval_hours, fixed_hours: report.fixed_hours, enabled: !report.enabled}}))}>{report.enabled ? "توقف" : "فعال‌سازی"}</button>
          <button className="btn-ghost" disabled={busy} onClick={() => void mutate(() => request(`/v1/scheduled-reports/${report.id}`, {method: "DELETE"}))}>آرشیو تعریف</button>
        </> : null}</div>
      </section>)}</div>
      {!reports.length && !loading ? <p className="card text-slate-500">گزارشی تعریف نشده است.</p> : null}
    </> : <>
      <div className="card grid gap-3 sm:grid-cols-3"><label>گزارش<select className="input mt-1" value={reportId} onChange={event => change({report: event.target.value, offset: null})}><option value="">همه گزارش‌ها</option>{reports.map(report => <option key={report.id} value={report.id}>{report.name}</option>)}</select></label><label>وضعیت<select className="input mt-1" value={status} onChange={event => change({status: event.target.value, offset: null})}><option value="">همه وضعیت‌ها</option>{Object.entries(statuses).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>روش اجرا<select className="input mt-1" value={trigger} onChange={event => change({trigger: event.target.value, offset: null})}><option value="">همه اجراها</option><option value="scheduled">زمان‌بندی‌شده</option><option value="manual">دستی</option></select></label></div>
      {detail && detail.id === selected ? <article className="card space-y-4">
        <header className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-bold">{detail.name}</h2><button className="btn-ghost" onClick={() => change({run: null})}>بستن گزارش</button></header>
        <p className="text-sm text-slate-500">{statuses[detail.status]} · {detail.trigger === "manual" ? "اجرای دستی" : "زمان‌بندی‌شده"} · {fmt.dateTime(detail.from_date)} تا {fmt.dateTime(detail.to_date)} · {detail.timezone}</p>
        {detail.content ? <MarkdownMessage content={detail.content}/> : <p role="status">{detail.error_detail || "گزارش در حال آماده‌سازی است…"}</p>}
        <details><summary className="cursor-pointer text-sm">معیارهای این اجرا</summary><p className="mt-2 whitespace-pre-wrap text-sm">{detail.instructions}</p></details>
        {detail.sources.length ? <div className="flex flex-wrap gap-2">{detail.sources.map(source => <Link className="btn-ghost" key={source.call_id} to={`/calls/${source.call_id}`}>مشاهده تماس {source.call_id.slice(0, 8)}</Link>)}</div> : null}
      </article> : null}
      <div className="space-y-3">{runs.map(run => <button className="card flex w-full flex-wrap items-center justify-between gap-3 text-right" key={run.id} onClick={() => change({run: run.id})}><span><strong className="block">{run.name}</strong><span className="text-xs text-slate-500">{fmt.dateTime(run.created_at)} · {run.trigger === "manual" ? "اجرای دستی" : "زمان‌بندی‌شده"}</span></span><span className={`text-sm ${run.status === "failed" ? "text-red-600" : "text-[#4B6E48]"}`}>{statuses[run.status]}</span></button>)}</div>
      {!runs.length && !loading ? <p className="card text-slate-500">گزارشی در این فیلتر وجود ندارد.</p> : null}
      <div className="flex items-center justify-between"><span className="text-sm">{fmt.int(total)} اجرا</span><div className="flex gap-2"><button className="btn-ghost" disabled={offset === 0} onClick={() => change({offset: String(Math.max(0, offset-25))})}>قبلی</button><button className="btn-ghost" disabled={offset + 25 >= total} onClick={() => change({offset: String(offset + 25)})}>بعدی</button></div></div>
    </>}
  </div>;
}
