import type { ReactNode } from "react";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import { fmt } from "../api";
import type { AssistantContextOptions, AssistantMessageAttachments } from "../types";

export type AssistantContextTab = "mentions" | "dates" | "tools";

const pad2 = (value: number) => String(value).padStart(2, "0");
const localStamp = (date: Date) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`;

const datePresets: Array<{ key: string; label: string; range: () => [Date, Date] }> = [
  { key: "today", label: "امروز", range: () => { const now = new Date(); return [new Date(now.getFullYear(), now.getMonth(), now.getDate()), now]; } },
  { key: "7d", label: "۷ روز اخیر", range: () => { const now = new Date(); return [new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7), now]; } },
  { key: "30d", label: "۳۰ روز اخیر", range: () => { const now = new Date(); return [new Date(now.getFullYear(), now.getMonth(), now.getDate() - 30), now]; } },
  { key: "90d", label: "۳ ماه اخیر", range: () => { const now = new Date(); return [new Date(now.getFullYear(), now.getMonth(), now.getDate() - 90), now]; } },
];

function CloseIcon() {
  return <svg className="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>;
}

export function AssistantAttachmentChips({ attachments, options, onChange }: {
  attachments: AssistantMessageAttachments;
  options: AssistantContextOptions | null;
  onChange: (value: AssistantMessageAttachments) => void;
}) {
  const chips: Array<{ key: string; kind: string; label: string; remove: () => void }> = [];
  if (attachments.operator_id) chips.push({ key: "operator", kind: "اپراتور", label: options?.operators.find((item) => item.id === attachments.operator_id)?.label || "انتخاب‌شده", remove: () => onChange({ ...attachments, operator_id: null }) });
  for (const id of attachments.conversation_ids) chips.push({ key: id, kind: "گفتگو", label: options?.conversations.find((item) => item.id === id)?.label || "انتخاب‌شده", remove: () => onChange({ ...attachments, conversation_ids: attachments.conversation_ids.filter((item) => item !== id) }) });
  if (attachments.from_date || attachments.to_date) chips.push({ key: "dates", kind: "بازه", label: attachments.from_date && attachments.to_date ? `${fmt.date(attachments.from_date)} تا ${fmt.date(attachments.to_date)}` : attachments.from_date ? `از ${fmt.date(attachments.from_date)}` : `تا ${fmt.date(attachments.to_date!)}`, remove: () => onChange({ ...attachments, from_date: null, to_date: null }) });
  if (!chips.length) return null;
  return <div className="assistant-attachment-list" aria-label="موارد انتخاب‌شده برای پیام">
    {chips.map((chip) => <button key={chip.key} type="button" className="assistant-attachment-chip" onClick={chip.remove} aria-label={`حذف ${chip.kind}: ${chip.label}`} title={`حذف ${chip.kind}: ${chip.label}`} data-kind={chip.kind}><em>{chip.kind}</em><span className="truncate">{chip.label}</span><CloseIcon /></button>)}
  </div>;
}

export default function AssistantContextPicker({ tab, onTabChange, onClose, attachments, onChange, children }: {
  tab: AssistantContextTab;
  onTabChange: (tab: AssistantContextTab) => void;
  onClose: () => void;
  attachments: AssistantMessageAttachments;
  onChange: (value: AssistantMessageAttachments) => void;
  options: AssistantContextOptions | null;
  children?: ReactNode;
}) {
  const hasDates = Boolean(attachments.from_date || attachments.to_date);
  const incomplete = hasDates && (!attachments.from_date || !attachments.to_date);
  const invalid = Boolean(attachments.from_date && attachments.to_date && new Date(attachments.from_date) >= new Date(attachments.to_date));
  const dateHint = incomplete ? "برای تکمیل بازه، هر دو تاریخ را انتخاب کنید." : invalid ? "تاریخ پایان را پس از تاریخ شروع انتخاب کنید." : hasDates ? "فقط داده‌های این بازه در پاسخ بررسی می‌شوند." : "تاریخ شروع و پایان را انتخاب کنید.";
  const selectedCount = (attachments.operator_id ? 1 : 0) + attachments.conversation_ids.length + (hasDates ? 1 : 0);
  const mentionCount = (attachments.operator_id ? 1 : 0) + attachments.conversation_ids.length;
  const tabCounts: Record<AssistantContextTab, number> = { mentions: mentionCount, dates: hasDates ? 1 : 0, tools: 0 };
  const title = tab === "dates" ? "بازه زمانی" : "انتخاب زمینه گفتگو";
  return <div className="assistant-context-panel" role="dialog" aria-label={title} dir="rtl" onKeyDown={(event) => { if (event.key === "Escape" && !(event.target as Element).closest("[data-date-picker-panel]")) { event.stopPropagation(); onClose(); } }}>
    <div className="assistant-context-heading"><h3>{title}</h3><button type="button" className="assistant-context-close" onClick={onClose} aria-label="بستن انتخاب زمینه"><CloseIcon /></button></div>
    <div className="assistant-context-tabs" role="group" aria-label="نوع زمینه پیام">
      {([["mentions", "زمینه‌ها"], ["dates", "بازه زمانی"]] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={tab === value} onClick={() => onTabChange(value)}>{label}{tabCounts[value] ? <span>{fmt.int(tabCounts[value])}</span> : null}</button>)}
    </div>
    <div className="assistant-context-body">
      {tab === "mentions" ? children : null}
      {tab === "dates" ? <>
        <p className="assistant-context-hint">بازه بررسی تماس‌ها و اطلاعات مرتبط را مشخص کنید.</p>
        <div className="assistant-date-presets" role="group" aria-label="بازه‌های آماده">
          {datePresets.map((preset) => <button key={preset.key} type="button" onClick={() => { const [from, to] = preset.range(); onChange({ ...attachments, from_date: localStamp(from), to_date: localStamp(to) }); }}>{preset.label}</button>)}
        </div>
        <div className={`assistant-date-range${incomplete || invalid ? " is-warn" : hasDates ? " is-set" : ""}`}>
          <div className="assistant-date-field"><p className="assistant-date-label">از تاریخ</p><JalaliDatePicker square includeTime value={attachments.from_date || ""} onChange={(value) => onChange({ ...attachments, from_date: value || null })} placeholder="انتخاب تاریخ شروع" /></div>
          <span className="assistant-date-arrow" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M19 12H5m6-6-6 6 6 6" /></svg></span>
          <div className="assistant-date-field"><p className="assistant-date-label">تا تاریخ</p><JalaliDatePicker square includeTime value={attachments.to_date || ""} onChange={(value) => onChange({ ...attachments, to_date: value || null })} placeholder="انتخاب تاریخ پایان" /></div>
        </div>
        <p className="assistant-date-hint" data-tone={incomplete || invalid ? "warn" : undefined} role="status"><span aria-hidden="true" />{dateHint}</p>
      </> : null}
    </div>
    <div className="assistant-context-footer">
      <span className="assistant-context-summary" role="status">{selectedCount ? `${fmt.int(selectedCount)} مورد انتخاب‌شده` : "موردی انتخاب نشده"}</span>
      {tab === "dates" ? <button type="button" className="assistant-context-clear" disabled={!hasDates} onClick={() => onChange({ ...attachments, from_date: null, to_date: null })}>پاک‌کردن بازه</button> : <span className="flex-1" />}
      <button type="button" className="assistant-context-done" disabled={tab === "dates" && (incomplete || invalid)} onClick={onClose}>تأیید انتخاب</button>
    </div>
  </div>;
}
