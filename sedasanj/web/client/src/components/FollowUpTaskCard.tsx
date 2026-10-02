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

function EditIcon({ close = false }: { close?: boolean }) {
  return close ? (
    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" aria-hidden="true">
      <path d="m5 5 10 10M15 5 5 15" />
    </svg>
  ) : (
    <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
      <path d="M12.8 3.2a2.1 2.1 0 0 1 3 3L7 15l-4 1 1-4Z" />
      <path d="m11.5 4.5 4 4" />
    </svg>
  );
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
    <li
      className={`border px-3 py-2.5 ${
        done ? "border-[#B2AC88] bg-[#B2AC88]/20" : "border-[#B2AC88] bg-[#F2F0EF]"
      }`}
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          role="checkbox"
          aria-checked={done}
          aria-label={done ? "بازگرداندن به انجام‌نشده" : "علامت انجام‌شده"}
          className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center border-2 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:opacity-50 ${
            done
              ? "border-[#4B6E48] bg-[#4B6E48] text-[#F2F0EF]"
              : "border-[#B2AC88] bg-[#F2F0EF] text-transparent"
          }`}
          disabled={!canEdit || saving}
          onClick={() => void toggleDone()}
        >
          <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
            <path d="m4 10 4 4 8-9" />
          </svg>
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex min-h-7 flex-wrap items-start justify-between gap-x-3 gap-y-1">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
              <p className={`min-w-0 text-sm font-medium leading-6 ${done ? "text-slate-400 line-through" : "text-slate-800"}`}>
                {task.title}
              </p>
              <span
                className={`badge px-1.5 py-0.5 text-[10px] ${
                  done ? "bg-[#4B6E48] text-[#F2F0EF]" : "bg-[#B2AC88] text-black"
                }`}
              >
                {TASK_STATUS_LABELS[task.status]}
              </span>
              {task.priority ? (
                <span className={`badge px-1.5 py-0.5 text-[10px] ${PRIORITY_TONE[task.priority] ?? "bg-slate-100 text-slate-600"}`}>
                  اولویت {TASK_PRIORITY_LABELS[task.priority]}
                </span>
              ) : null}
              {overdue ? <span className="badge bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-700">عقب‌افتاده</span> : null}
            </div>
            {canEdit ? (
              <button
                type="button"
                className={`inline-flex h-7 w-7 shrink-0 items-center justify-center border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] ${
                  open
                    ? "border-[#4B6E48] bg-[#4B6E48] text-[#F2F0EF]"
                    : "border-[#B2AC88] text-[#4B6E48] hover:bg-[#B2AC88]/40"
                }`}
                aria-label={open ? "بستن ویرایش" : "ویرایش کار"}
                title={open ? "بستن ویرایش" : "ویرایش"}
                onClick={() => setOpen((current) => !current)}
              >
                <EditIcon close={open} />
              </button>
            ) : null}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
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
            <p className={`mt-1.5 text-xs leading-5 ${done ? "text-slate-400" : "text-slate-600"}`}>
              {task.description}
            </p>
          ) : null}
          {showCallLink ? (
            <div className="mt-1.5 flex items-center">
              <Link className="text-xs text-brand-700 hover:underline" to={`/calls/${task.call_id}`}>
                مشاهده تماس
              </Link>
            </div>
          ) : null}
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
