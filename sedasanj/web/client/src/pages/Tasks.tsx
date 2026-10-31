import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { FilterSelect, useFilterBar, type FilterBarField } from "@cbi/web-shared/components/FilterBar";
import { PageHeader } from "../components/PageHeader";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import { fmt, request, TASK_PRIORITY_LABELS, TASK_STATUS_LABELS } from "../api";
import { CAN_EDIT_TASKS, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import TaskDetails from "../components/TaskDetails";
import TaskCreateDialog from "../components/TaskCreateDialog";
import { useTablePageSize } from "../lib/useTablePagination";
import type { TaskPage, TaskPerson } from "../types";

const VIEWS = [{ id: "overdue", label: "عقب‌افتاده" }, { id: "today", label: "امروز" }, { id: "upcoming", label: "آینده" }, { id: "done", label: "انجام‌شده" }, { id: "all", label: "همه" }];
const SORTS = [{ id: "due_date", label: "موعد" }, { id: "priority", label: "اولویت" }, { id: "created_at", label: "زمان ایجاد" }, { id: "updated_at", label: "آخرین تغییر" }];
function numberParam(value: string | null) { const n = Number(value); return Number.isSafeInteger(n) && n >= 0 ? n : 0; }
export default function Tasks() {
  const { session } = useAuth();
  const canEdit = Boolean(session && CAN_EDIT_TASKS.includes(session.role));
  const isAdmin = session?.role === "org_admin";
  const [params, setParams] = useSearchParams();
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const [pageSize] = useTablePageSize();
  const view = VIEWS.some((v) => v.id === params.get("view")) ? params.get("view")! : "today";
  const offset = numberParam(params.get("offset"));
  const selected = params.get("task");
  const [page, setPage] = useState<TaskPage | null>(null);
  const [people, setPeople] = useState<TaskPerson[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState(params.get("q") ?? "");
  const querySearch = params.get("q") ?? "";
  useEffect(() => { setSearch(querySearch); }, [querySearch]);
  function change(values: Record<string, string>, reset = true, replace = false) {
    setParams(() => {
      const next = new URLSearchParams(paramsRef.current);
      if (reset) next.delete("offset");
      Object.entries(values).forEach(([key, value]) => { if (value) next.set(key, value); else next.delete(key); });
      paramsRef.current = next;
      return next;
    }, { replace });
  }
  useEffect(() => {
    if (search === querySearch) return;
    const timer = setTimeout(() => change({ q: search.trim() }, true, true), 350);
    return () => clearTimeout(timer);
  }, [search, querySearch]);
  useEffect(() => {
    let active = true;
    void request<TaskPerson[]>("/v1/tasks/people").then((next) => { if (active) setPeople(next); }).catch(() => {});
    return () => { active = false; };
  }, []);
  const apiParams = new URLSearchParams({ view, limit: String(pageSize), offset: String(offset) });
  for (const key of ["q", "status", "priority", "due_from", "due_to", "sort", "order"]) {
    const value = params.get(key);
    if (value) apiParams.set(key, value);
  }
  const assignee = params.get("assignee") ?? "";
  if (assignee === "unassigned") apiParams.set("unassigned", "true");
  else if (assignee) apiParams.set("assignee_id", assignee);
  const query = apiParams.toString();
  useEffect(() => {
    let active = true;
    setLoading(true); setError(null);
    void request<TaskPage>(`/v1/tasks?${query}`).then((next) => {
      if (!active) return;
      if (offset > 0 && !next.items.length) {
        change({ offset: String(Math.max(0, Math.floor((next.total - 1) / pageSize) * pageSize)) }, false, true);
        return;
      }
      setPage(next);
    }).catch(() => { if (active) { setPage(null); setError("دریافت کارها ممکن نشد؛ فیلترها و اتصال را بررسی و دوباره تلاش کنید."); } })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [query, revision]);
  const filterKeys = ["q", "status", "priority", "assignee", "due_from", "due_to", "sort", "order"];
  const clearFilters = () => { setSearch(""); change(Object.fromEntries(filterKeys.map((key) => [key, ""]))); };
  const selectField = (id: string, label: string, options: { value: string; label: string }[]): FilterBarField => ({
    id, label, active: Boolean(params.get(id)), onRemove: () => change({ [id]: "" }),
    control: <FilterSelect ariaLabel={label} value={params.get(id) ?? ""} onChange={(value) => change({ [id]: value })} options={options} />,
  });
  const filterFields: FilterBarField[] = [
    selectField("status", "وضعیت", Object.entries(TASK_STATUS_LABELS).map(([value, label]) => ({ value, label }))),
    selectField("assignee", "مسئول", [{ value: "unassigned", label: "بدون مسئول" }, ...people.map((p) => ({ value: p.id, label: p.name })), ...(assignee && assignee !== "unassigned" && !people.some((p) => p.id === assignee) ? [{ value: assignee, label: "مسئول انتخاب‌شده" }] : [])]),
    selectField("priority", "اولویت", Object.entries(TASK_PRIORITY_LABELS).map(([value, label]) => ({ value, label }))),
    ...[{ id: "due_from", label: "موعد از" }, { id: "due_to", label: "موعد تا" }].map(({ id, label }) => ({
      id, label, active: Boolean(params.get(id)), onRemove: () => change({ [id]: "" }),
      control: <JalaliDatePicker value={params.get(id) ?? ""} onChange={(value) => change({ [id]: value })} placeholder="انتخاب تاریخ" />,
    })),
    { id: "sort", label: "مرتب‌سازی", pinned: true, active: Boolean(params.get("sort")), onRemove: () => {},
      control: <FilterSelect ariaLabel="مرتب‌سازی" allLabel={null} value={params.get("sort") ?? "due_date"} onChange={(value) => change({ sort: value })} options={SORTS.map((s) => ({ value: s.id, label: s.label }))} /> },
    { id: "order", label: "ترتیب", pinned: true, active: Boolean(params.get("order")), onRemove: () => {},
      control: <FilterSelect ariaLabel="ترتیب" allLabel={null} value={params.get("order") ?? "asc"} onChange={(value) => change({ order: value })} options={[{ value: "asc", label: "صعودی" }, { value: "desc", label: "نزولی" }]} /> },
  ];
  const filterBar = useFilterBar({ fields: filterFields, hasActive: filterKeys.some((key) => Boolean(params.get(key))), onClear: clearFilters });
  return <div className="space-y-4">
    <PageHeader title="کارهای قابل پیگیری" description="مدیریت کارهای تماس، مسئول‌ها و روند پیگیری" actions={<div className="flex flex-wrap items-center justify-end gap-3">{filterBar.toolbar}<button type="button" className="btn-ghost" disabled={loading} onClick={() => setRevision((v) => v + 1)}>تازه‌سازی</button>{canEdit ? <button type="button" className="btn" onClick={() => setCreating(true)}>ثبت کار جدید</button> : null}</div>} />
    {creating ? <TaskCreateDialog onCancel={() => setCreating(false)} onCreated={(task) => { setCreating(false); change({ task: task.id, history_offset: "" }, false); setRevision((v) => v + 1); }} /> : null}
    <nav className="panel-tabs grid-cols-2 sm:grid-cols-5" aria-label="صف کارها">{VIEWS.map((item) => <button key={item.id} type="button" aria-current={view === item.id ? "page" : undefined} onClick={() => change({ view: item.id })} className="panel-tab"><span className="block text-lg font-light">{page ? fmt.int(page.counts[item.id] ?? 0) : "—"}</span><span className="text-sm">{item.label}</span></button>)}</nav>
    <div className="card">
      <label className="block max-w-lg"><span className="sr-only">جست‌وجو در کارها</span><input className="input" type="search" placeholder="جست‌وجوی عنوان، توضیحات یا شماره تماس" maxLength={200} value={search} onChange={(e) => setSearch(e.target.value)} /></label>
    </div>
    {filterBar.fields}
    <ErrorBox message={error} />
    <div className={`grid items-start gap-4 ${selected ? "lg:grid-cols-[minmax(0,1fr)_minmax(340px,42%)]" : ""}`}>
      <section tabIndex={-1} className="card min-w-0" aria-label="فهرست کارها" aria-busy={loading}>
        {loading ? <Loading /> : page?.items.length ? <div className="overflow-x-auto"><table className="table" dir="rtl"><thead><tr><th>عنوان کار</th><th>وضعیت</th>{!selected ? <><th>مسئول</th><th>اولویت</th><th>موعد</th><th>شماره تماس</th><th>آخرین تغییر</th></> : null}</tr></thead><tbody>{page.items.map((task) => {
          const overdue = task.status !== "done" && task.due_date && task.due_date < page.today;
          const open = () => change({ task: task.id, history_offset: "" }, false);
          return <tr key={task.id} tabIndex={0} role="button" aria-label={task.title} aria-current={selected === task.id ? "true" : undefined} className={`table-row-link ${selected === task.id ? "bg-brand-50" : ""}`} onClick={open} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }}>
            <td><span className="block max-w-xs whitespace-normal leading-6">{task.title}</span>{selected ? <div className="mt-2 max-w-xs space-y-1 whitespace-normal text-xs text-slate-500"><p>مسئول: {task.assignee_name ?? "تعیین نشده"} · اولویت: {task.priority ? TASK_PRIORITY_LABELS[task.priority] : "—"}</p><p className={overdue ? "text-rose-700" : undefined}>موعد: {task.due_date ? fmt.calendarDate(task.due_date) : "بدون موعد"}{overdue ? " · عقب‌افتاده" : ""}</p><p><bdi dir="ltr">{task.source_phone ?? "—"}</bdi> · {fmt.dateTime(task.updated_at)}</p>{isAdmin && !task.assignee_access_valid ? <p className="text-rose-700">مسئول فاقد دسترسی به تماس</p> : null}</div> : null}</td>
            <td><span className={`badge ${task.status === "done" ? "badge-success" : task.status === "in_progress" ? "badge-info" : "badge-neutral"}`}>{TASK_STATUS_LABELS[task.status]}</span></td>
            {!selected ? <><td>{task.assignee_name ?? "تعیین نشده"}{isAdmin && !task.assignee_access_valid ? <span className="block text-xs text-rose-700">فاقد دسترسی به تماس</span> : null}</td>
            <td>{task.priority ? TASK_PRIORITY_LABELS[task.priority] : "—"}</td>
            <td className={overdue ? "text-rose-700" : undefined}>{task.due_date ? fmt.calendarDate(task.due_date) : "بدون موعد"}{overdue ? <span className="block text-xs">عقب‌افتاده</span> : null}</td>
            <td><bdi dir="ltr">{task.source_phone ?? "—"}</bdi></td><td>{fmt.dateTime(task.updated_at)}</td></> : null}
          </tr>;
        })}</tbody></table></div> : !error ? <Empty>کاری در این نما نیست؛ فیلترها را تغییر دهید یا کار جدید ثبت کنید.</Empty> : null}
        <Pagination page={Math.floor(offset / pageSize) + 1} total={page?.total} loading={loading} hasPrevious={offset > 0} hasNext={Boolean(page && offset + pageSize < page.total)} onPrevious={() => change({ offset: String(Math.max(0, offset - pageSize)) }, false)} onNext={() => change({ offset: String(offset + pageSize) }, false)} />
      </section>
      {selected ? <TaskDetails key={selected} id={selected} canEdit={canEdit} isAdmin={isAdmin} historyOffset={numberParam(params.get("history_offset"))} onHistoryOffset={(offset) => change({ history_offset: offset ? String(offset) : "" }, false)} onUpdated={() => setRevision((v) => v + 1)} onClose={() => change({ task: "", history_offset: "" }, false)} /> : null}
    </div>
  </div>;
}
