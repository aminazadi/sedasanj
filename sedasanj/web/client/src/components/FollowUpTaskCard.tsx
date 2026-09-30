import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request, TASK_PRIORITY_LABELS, TASK_STATUS_LABELS } from "../api";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import type { FollowUpTask, TaskPriority, TaskStatus } from "../types";

const PRIORITY_TONE: Record<string, string> = {
  high: "bg-rose-50 text-rose-700",
  normal: "bg-amber-50 text-amber-700",
  low: "bg-slate-100 text-slate-600",
};

interface Draft {
  title: string;
  description: string;
  priority: string;
  due_date: string;
}

function toDraft(task: FollowUpTask): Draft {
  return {
    title: task.title,
    description: task.description ?? "",
    priority: task.priority ?? "",
    due_date: task.due_date ?? "",
  };
}

function tehranToday(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tehran",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const pick = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")}`;
}

function parties(task: FollowUpTask): string {
  const caller = task.caller_number ? fmt.digits(task.caller_number) : "—";
  const dialed = task.dialed_number ? fmt.digits(task.dialed_number) : "—";
  return `${caller} → ${dialed}`;
}

export default function FollowUpTaskCard({
  task,
  canEdit,
  showCallLink = true,
  onUpdated,
}: {
  task: FollowUpTask;
  canEdit: boolean;
  showCallLink?: boolean;
  onUpdated: (next: FollowUpTask) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => toDraft(task));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const done = task.status === "done";
  const overdue = !done && Boolean(task.due_date) && task.due_date! < tehranToday();
  const dirty =
    draft.title !== task.title ||
    draft.description !== (task.description ?? "") ||
    draft.priority !== (task.priority ?? "") ||
    draft.due_date !== (task.due_date ?? "");

  useEffect(() => {
    setDraft(toDraft(task));
    setError(null);
  }, [task]);

  async function patch(body: Partial<{
    title: string;
    description: string | null;
    status: TaskStatus;
    priority: TaskPriority | null;
    due_date: string | null;
  }>) {
    setSaving(true);
    setError(null);
    try {
      const next = await request<FollowUpTask>(`/v1/tasks/${task.id}`, {
        method: "PATCH",
        body,
      });
      onUpdated(next);
      return next;
    } catch (err) {
      setError((err as Error).message);
      throw err;
    } finally {
      setSaving(false);
    }
  }

  async function toggleDone() {
    try {
      await patch({ status: done ? "open" : "done" });
    } catch {
      /* surfaced via error */
    }
  }

  async function saveEdits() {
    const title = draft.title.trim();
    if (!title) {
      setError("عنوان کار نمی‌تواند خالی باشد.");
      return;
    }
    try {
      await patch({
        title,
        description: draft.description.trim() ? draft.description.trim() : null,
        priority: (draft.priority || null) as TaskPriority | null,
        due_date: draft.due_date || null,
      });
      setOpen(false);
    } catch {
      /* surfaced via error */
    }
  }

  return (
    <li className={`rounded-xl border p-3 ${done ? "border-slate-100 bg-slate-50/70" : "border-slate-200 bg-white"}`}>
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          className="mt-1 h-4 w-4 rounded border-slate-300 accent-brand-500 disabled:opacity-50"
          checked={done}
          disabled={!canEdit || saving}
          onChange={() => void toggleDone()}
          aria-label={done ? "بازگرداندن به انجام‌نشده" : "علامت انجام‌شده"}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className={`text-sm leading-6 ${done ? "text-slate-400 line-through" : "text-slate-800"}`}>
              {task.title}
            </p>
            <div className="flex flex-wrap items-center gap-1">
              <span className={`badge ${done ? "bg-emerald-50 text-emerald-700" : "bg-brand-50 text-brand-700"}`}>
                {TASK_STATUS_LABELS[task.status]}
              </span>
              {task.priority ? (
                <span className={`badge ${PRIORITY_TONE[task.priority] ?? "bg-slate-100 text-slate-600"}`}>
                  اولویت {TASK_PRIORITY_LABELS[task.priority]}
                </span>
              ) : null}
              {overdue ? <span className="badge bg-rose-50 text-rose-700">عقب‌افتاده</span> : null}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            <span>ایجاد: {fmt.dateTime(task.created_at)}</span>
            {task.due_date ? (
              <span className={overdue ? "text-rose-600" : undefined}>
                موعد: {fmt.calendarDate(task.due_date)}
              </span>
            ) : (
              <span>بدون موعد</span>
            )}
            <span dir="ltr">طرفین: {parties(task)}</span>
            {task.source_phone ? (
              <span>
                شماره مبدأ: <span dir="ltr">{fmt.digits(task.source_phone)}</span>
              </span>
            ) : null}
            {task.agent_extension ? <span>داخلی: {fmt.digits(task.agent_extension)}</span> : null}
          </div>
          {task.description ? (
            <p className={`mt-2 text-xs leading-6 ${done ? "text-slate-400" : "text-slate-600"}`}>
              {task.description}
            </p>
          ) : null}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {canEdit ? (
              <button type="button" className="btn-ghost text-xs" onClick={() => setOpen((current) => !current)}>
                {open ? "بستن ویرایش" : "ویرایش"}
              </button>
            ) : null}
            {showCallLink ? (
              <Link className="text-xs text-brand-700 hover:underline" to={`/calls/${task.call_id}`}>
                مشاهده تماس
              </Link>
            ) : null}
          </div>
          {error ? <p className="mt-2 text-xs text-rose-600">{error}</p> : null}
          {open && canEdit ? (
            <div className="mt-3 grid gap-3 rounded-xl border border-slate-100 bg-slate-50 p-3 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className="label">عنوان</label>
                <input
                  className="input"
                  value={draft.title}
                  onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                />
              </div>
              <div className="md:col-span-2">
                <label className="label">توضیحات اپراتور</label>
                <textarea
                  className="input min-h-24"
                  value={draft.description}
                  onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                />
              </div>
              <div>
                <label className="label">موعد انجام</label>
                <JalaliDatePicker
                  value={draft.due_date}
                  onChange={(due_date) => setDraft({ ...draft, due_date })}
                  placeholder="بدون موعد"
                />
              </div>
              <div>
                <label className="label">اولویت</label>
                <select
                  className="input"
                  value={draft.priority}
                  onChange={(event) => setDraft({ ...draft, priority: event.target.value })}
                >
                  <option value="">بدون اولویت</option>
                  <option value="high">بالا</option>
                  <option value="normal">معمولی</option>
                  <option value="low">پایین</option>
                </select>
              </div>
              <div className="md:col-span-2 flex flex-wrap gap-2">
                <button type="button" className="btn" disabled={saving || !dirty} onClick={() => void saveEdits()}>
                  {saving ? "در حال ذخیره…" : "ذخیره تغییرات"}
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={saving}
                  onClick={() => {
                    setDraft(toDraft(task));
                    setOpen(false);
                  }}
                >
                  انصراف
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}
