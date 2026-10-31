import { taskErrorText } from "../lib/taskErrors";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import { fmt, request, TASK_PRIORITY_LABELS, TASK_STATUS_LABELS } from "../api";
import type { FollowUpTask, TaskHistoryPage, TaskPerson } from "../types";

const FIELDS: Record<string, string> = { title: "عنوان", description: "توضیحات", status: "وضعیت", priority: "اولویت", due_date: "موعد", assignee_id: "مسئول" };
export default function TaskDetails({ id, canEdit, isAdmin, historyOffset, onHistoryOffset, onUpdated, onClose }: {
  id: string; canEdit: boolean; isAdmin: boolean; historyOffset: number;
  onHistoryOffset: (offset: number) => void; onUpdated: () => void; onClose: () => void;
}) {
  const [task, setTask] = useState<FollowUpTask | null>(null);
  const [history, setHistory] = useState<TaskHistoryPage | null>(null);
  const [people, setPeople] = useState<TaskPerson[]>([]);
  const [revision, setRevision] = useState(0);
  const [draft, setDraft] = useState({ title: "", description: "", priority: "", due_date: "", status: "open", assignee_id: "" });
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 1023px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1023px)");
    const changed = () => setMobile(media.matches);
    media.addEventListener("change", changed);
    return () => media.removeEventListener("change", changed);
  }, []);
  useEffect(() => {
    if (!mobile) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [mobile]);
  const generation = useRef(0);
  useEffect(() => {
    generation.current += 1;
    setNote("");
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    return () => { generation.current += 1; if (previous?.isConnected) previous.focus(); else document.querySelector<HTMLElement>('[aria-label="فهرست کارها"]')?.focus(); };
  }, [id]);
  useEffect(() => {
    let active = true;
    setSaving(false);
    setLoading(true); setError(null); setPeople([]); setTask(null);
    void request<FollowUpTask>(`/v1/tasks/${id}`).then(async (next) => {
      if (!active) return;
      setTask(next); setDraft({ title: next.title, description: next.description ?? "", priority: next.priority ?? "", due_date: next.due_date ?? "", status: next.status, assignee_id: next.assignee_id ?? "" });
      if (isAdmin) {
        const list = await request<TaskPerson[]>(`/v1/tasks/assignees?call_id=${next.call_id}`);
        if (active) setPeople(list);
      }
    }).catch((err: unknown) => { if (active) setError(taskErrorText(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, revision, isAdmin]);
  useEffect(() => {
    let active = true; setHistory(null); setHistoryError(false);
    void request<TaskHistoryPage>(`/v1/tasks/${id}/history?limit=25&offset=${historyOffset}`)
      .then((next) => {
        if (!active) return;
        if (historyOffset > 0 && !next.items.length) { onHistoryOffset(Math.max(0, Math.floor((next.total - 1) / 25) * 25)); return; }
        setHistory(next);
      }).catch(() => { if (active) setHistoryError(true); });
    return () => { active = false; };
  }, [id, historyOffset, revision]);
  async function mutate(kind: "edit" | "note") {
    if (!task) return;
    const currentGeneration = generation.current;
    setSaving(true); setError(null);
    const body = kind === "note" ? { note: note.trim(), version: task.version } : {
      title: draft.title.trim(), description: draft.description.trim() || null,
      priority: draft.priority || null, due_date: draft.due_date || null, status: draft.status,
      ...(isAdmin ? { assignee_id: draft.assignee_id || null } : {}), version: task.version,
    };
    try {
      await request<FollowUpTask>(`/v1/tasks/${task.id}${kind === "note" ? "/notes" : ""}`, { method: kind === "note" ? "POST" : "PATCH", body });
      onUpdated();
      if (currentGeneration !== generation.current) return;
      if (kind === "note") setNote("");
      onHistoryOffset(0); setRevision((v) => v + 1);
    } catch (err) { if (currentGeneration === generation.current) setError(taskErrorText(err)); }
    finally { if (currentGeneration === generation.current) setSaving(false); }
  }
  function value(field: string, input: unknown): string {
    if (input === null || input === "") return "—";
    if (field === "status") return TASK_STATUS_LABELS[String(input)] ?? String(input);
    if (field === "priority") return TASK_PRIORITY_LABELS[String(input)] ?? String(input);
    if (field === "due_date") return fmt.calendarDate(String(input));
    if (field === "assignee_id") return people.find((p) => p.id === input)?.name ?? (task?.assignee_id === input ? task?.assignee_name : null) ?? "کاربر پیشین";
    return String(input);
  }
  return <aside ref={panel} role={mobile ? "dialog" : "complementary"} aria-modal={mobile ? true : undefined} tabIndex={-1} aria-label="جزئیات و پیگیری کار" className="fixed inset-0 z-[80] overflow-y-auto bg-[#F2F0EF] p-4 outline-none lg:sticky lg:inset-auto lg:top-4 lg:z-auto lg:max-h-[calc(100vh-2rem)] lg:card" onKeyDown={(event) => {
    if (event.key === "Escape" && !saving) onClose();
    if (event.key === "Tab" && window.matchMedia("(max-width: 1023px)").matches) {
      const controls = panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a, input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]');
      if (!controls?.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }}>
    <div className="mb-4 flex items-center justify-between gap-3"><h2 className="text-lg font-bold">جزئیات و پیگیری</h2><button className="btn-ghost" type="button" disabled={saving} onClick={onClose}>بستن</button></div>
    {error ? <p role="alert" className="mb-3 text-sm leading-6 text-rose-700">{error}</p> : null}
    <button type="button" className="btn-ghost mb-3 text-xs" disabled={saving || loading} onClick={() => setRevision((v) => v + 1)}>دریافت نسخه تازه</button>
    {loading ? <p role="status">در حال دریافت…</p> : task ? <>
      <div className="mb-4 space-y-2 border-y border-[color:var(--line)] py-3 text-xs text-slate-600">
        <p>ایجاد: {fmt.dateTime(task.created_at)} · {task.origin === "manual" ? "ثبت دستی" : "تحلیل تماس"}</p>
        <p>آخرین تغییر: {fmt.dateTime(task.updated_at)} · نسخه {fmt.int(task.version)}</p>
        <p>طرفین: <bdi dir="ltr">{task.caller_number ?? "—"} → {task.dialed_number ?? "—"}</bdi></p>
        {task.completed_at ? <p>تکمیل: {fmt.dateTime(task.completed_at)}</p> : null}
        <Link className="inline-block text-brand-700 underline" to={`/calls/${task.call_id}`}>مشاهده تماس مرتبط</Link>
        {isAdmin && !task.assignee_access_valid ? <p role="status" className="text-rose-700">مسئول فعلی به تماس دسترسی ندارد؛ مسئول دیگری انتخاب کنید.</p> : null}
      </div>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void mutate("edit"); }}>
        <fieldset className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2" disabled={!canEdit || saving}>
          <label className="sm:col-span-2 lg:col-span-1 xl:col-span-2">عنوان<input className="input mt-1" maxLength={500} required value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
          <label className="sm:col-span-2 lg:col-span-1 xl:col-span-2">توضیحات<textarea className="input mt-1 min-h-24" maxLength={4000} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
          <label>وضعیت<select className="input" value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })}>{Object.entries(TASK_STATUS_LABELS).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
          <label>اولویت<select className="input" value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })}><option value="">بدون اولویت</option>{Object.entries(TASK_PRIORITY_LABELS).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
          <label>موعد<JalaliDatePicker value={draft.due_date} onChange={(due_date) => setDraft({ ...draft, due_date })} placeholder="بدون موعد" /></label>
          {isAdmin ? <label>مسئول<select className="input" value={draft.assignee_id} onChange={(e) => setDraft({ ...draft, assignee_id: e.target.value })}><option value="">تعیین نشده</option>{task.assignee_id && !people.some((p) => p.id === task.assignee_id) ? <option value={task.assignee_id} disabled>{task.assignee_name ?? "مسئول قبلی"} · فاقد دسترسی</option> : null}{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label> : <p className="text-sm">مسئول: {task.assignee_name ?? "تعیین نشده"}</p>}
        </fieldset>
        {canEdit ? <button className="btn" disabled={saving || !draft.title.trim()}>ذخیره تغییرات</button> : null}
      </form>
      <section className="mt-6 border-t border-[color:var(--line)] pt-4"><h3 className="mb-3 text-base font-bold">یادداشت پیگیری</h3>
        {canEdit ? <form onSubmit={(e) => { e.preventDefault(); void mutate("note"); }} className="space-y-2"><label className="sr-only" htmlFor="task-note">متن یادداشت پیگیری</label><textarea id="task-note" className="input min-h-24" maxLength={4000} disabled={saving} value={note} onChange={(e) => setNote(e.target.value)} placeholder="نتیجه تماس یا قدم بعدی را ثبت کنید…" /><button className="btn" disabled={saving || !note.trim()}>ثبت یادداشت</button><p className="text-xs text-slate-500">یادداشت پس از ثبت قابل ویرایش یا حذف نیست.</p></form> : null}
      </section>
      <section className="mt-6 border-t border-[color:var(--line)] pt-4"><h3 className="mb-3 text-base font-bold">تاریخچه پیگیری</h3>
        {historyError ? <p role="alert">دریافت تاریخچه ممکن نشد؛ دریافت نسخه تازه را بزنید.</p> : !history ? <p role="status">در حال دریافت تاریخچه…</p> : <>
          {!history.items.length ? <p className="text-sm text-slate-500">هنوز رویدادی ثبت نشده است.</p> : <ol className="space-y-3 border-r border-[color:var(--line)] pr-3">{history.items.map((e) => <li key={e.id} className="border-b border-[color:var(--line)] pb-3 text-sm"><p className="text-xs text-slate-500">{e.actor_name ?? "سیستم"} · {fmt.dateTime(e.created_at)}</p><p className="mt-1">{e.kind === "created" ? "کار ایجاد شد" : e.kind === "note" ? "یادداشت پیگیری" : "کار به‌روزرسانی شد"}</p>{e.note ? <p className="mt-2 whitespace-pre-wrap break-words leading-6">{e.note}</p> : null}{Object.entries(e.changes).map(([field, change]) => <p key={field} className="mt-1 break-words text-xs leading-6">{FIELDS[field] ?? field}: <del>{value(field, change.before)}</del> ← {value(field, change.after)}</p>)}</li>)}</ol>}
          <div className="mt-3 flex items-center justify-between gap-2 text-xs"><button type="button" className="btn-ghost" disabled={!historyOffset} onClick={() => onHistoryOffset(Math.max(0, historyOffset - 25))}>قبلی</button><span>{fmt.int(history.total)} رویداد · صفحه {fmt.int(Math.floor(historyOffset / 25) + 1)}</span><button type="button" className="btn-ghost" disabled={historyOffset + 25 >= history.total} onClick={() => onHistoryOffset(historyOffset + 25)}>بعدی</button></div>
        </>}
      </section>
    </> : null}
  </aside>;
}
