import SearchSelect from "./SearchSelect";
import FormDialog from "./FormDialog";
import taskArt from "../assets/scheduled-report.webp";
import { taskErrorText } from "../lib/taskErrors";
import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import type { CallSummary, FollowUpTask } from "../types";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";

export default function TaskCreateDialog({ callId, onCreated, onCancel }: {
  callId?: string; onCreated: (task: FollowUpTask) => void; onCancel: () => void;
}) {
  const [selectedLabel, setSelectedLabel] = useState("");
  const [selected, setSelected] = useState(callId ?? "");
  const [search, setSearch] = useState("");
  const [calls, setCalls] = useState<CallSummary[]>([]);
  const [callsOffset, setCallsOffset] = useState(0);
  const [callsError, setCallsError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [priority, setPriority] = useState("");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (callId) return;
    let active = true;
    setLoading(true);
    setCallsError(null);
    const timer = setTimeout(() => {
      void request<{ items: CallSummary[]; total: number }>(`/v1/calls?limit=10&offset=${callsOffset}&q=${encodeURIComponent(search)}`)
        .then((page) => { if (active) { setCalls(page.items.filter((c) => c.direction !== "internal")); setHasMore(callsOffset + 10 < page.total); } })
        .catch(() => { if (active) setCallsError("دریافت تماس‌ها ممکن نشد؛ دوباره تلاش کنید."); })
        .finally(() => { if (active) setLoading(false); });
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [callId, search, callsOffset, retry]);
  async function save() {
    if (!selected || !title.trim()) return;
    setSaving(true); setError(null);
    try {
      const task = await request<FollowUpTask>("/v1/tasks", { method: "POST", body: {
        call_id: selected, title: title.trim(), description: description.trim() || null,
        due_date: dueDate || null, priority: priority || null,
      } });
      onCreated(task);
    } catch (err) { setError(taskErrorText(err)); }
    finally { setSaving(false); }
  }
  return <FormDialog open title="ثبت کار جدید" description="برای تماس مشتری یک کار و موعد پیگیری ثبت کنید." art={taskArt} submitLabel="ثبت کار" busy={saving} submitDisabled={!selected || !title.trim()} error={error} onClose={onCancel} onSubmit={() => void save()} wide>
    {!callId ? <div className="grid gap-2">
      <span className="label">تماس مرتبط</span>
      <SearchSelect
        ariaLabel="تماس مرتبط"
        options={calls.map((call) => ({ value: call.id, label: `${call.caller_number ?? "—"} ← ${call.dialed_number ?? "—"} · ${fmt.dateTime(call.started_at)}` }))}
        value={selected}
        selectedLabel={selectedLabel || undefined}
        onChange={(value) => {
          setSelected(value);
          const call = calls.find((item) => item.id === value);
          setSelectedLabel(call ? `${call.caller_number ?? "—"} ← ${call.dialed_number ?? "—"} · ${fmt.dateTime(call.started_at)}` : "");
        }}
        emptyLabel="انتخاب تماس مشتری"
        searchPlaceholder="جست‌وجوی شماره یا عبارت تماس"
        onSearchChange={(term) => {
          if (term !== search || callsOffset !== 0) setLoading(true);
          setSearch(term); setCallsOffset(0);
        }}
        disabled={saving}
        loading={loading}
        error={callsError}
        onRetry={() => { setLoading(true); setRetry((value) => value + 1); }}
        pagination={{
          hasPrevious: callsOffset > 0,
          hasNext: hasMore,
          onPrevious: () => { setLoading(true); setCallsOffset(Math.max(0, callsOffset - 10)); },
          onNext: () => { setLoading(true); setCallsOffset(callsOffset + 10); },
        }}
      />
    </div> : null}
    <fieldset className="grid gap-3 sm:grid-cols-2" disabled={saving}>
      <label className="sm:col-span-2"><span>عنوان</span><input className="input mt-1" required maxLength={500} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label className="sm:col-span-2"><span>توضیحات</span><textarea className="input mt-1" maxLength={4000} value={description} onChange={(e) => setDescription(e.target.value)} /></label>
      <label><span>موعد</span><JalaliDatePicker value={dueDate} onChange={setDueDate} placeholder="بدون موعد" /></label>
      <label><span>اولویت</span><select className="input" value={priority} onChange={(e) => setPriority(e.target.value)}><option value="">بدون اولویت</option><option value="high">بالا</option><option value="normal">معمولی</option><option value="low">پایین</option></select></label>
    </fieldset>
  </FormDialog>;
}
