import { useEffect, useRef, useState } from "react";
import ConfirmDialog from "./ConfirmDialog";
import { fmt } from "../api";
import { runBulkAction } from "../lib/bulkActions.mjs";

export interface BulkAction {
  label: string;
  destructive?: boolean;
  eligible: (id: string) => boolean;
  execute: (id: string) => Promise<unknown>;
}

export function SelectionCheckbox({ checked, mixed = false, disabled, label, onChange }: {
  checked: boolean; mixed?: boolean; disabled: boolean; label: string; onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = mixed; }, [mixed]);
  return <input ref={ref} type="checkbox" className="h-4 w-4 accent-[#4B6E48]" aria-label={label}
    checked={checked} disabled={disabled} onChange={onChange}
    onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()} />;
}

export function useBulkSelection(scope: string) {
  const [selection, setSelection] = useState<{ scope: string; ids: string[] }>({ scope, ids: [] });
  useEffect(() => { setSelection({ scope, ids: [] }); }, [scope]);
  const selected = selection.scope === scope ? selection.ids : [];
  const setSelected = (ids: string[]) => setSelection({ scope, ids });
  return { selected, setSelected, toggle: (id: string) => setSelected(selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id]) };
}

export default function BulkActions({ selected, setSelected, actions, onComplete, onBusy, disabled = false }: {
  selected: string[]; setSelected: (ids: string[]) => void; actions: BulkAction[];
  onComplete: () => void; onBusy: (busy: boolean) => void; disabled?: boolean;
}) {
  const [pending, setPending] = useState<BulkAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<string | null>(null);
  const [failures, setFailures] = useState<{ id: string; message: string }[]>([]);
  async function run(action: BulkAction) {
    if (busy) return;
    const ids = selected.filter(action.eligible);
    const skipped = selected.filter((id) => !action.eligible(id));
    setBusy(true); onBusy(true); setProgress(0); setResult(null); setFailures([]);
    try {
      const outcome = await runBulkAction(ids, action.execute, setProgress);
      setSelected([...skipped, ...outcome.failed.map((item) => item.id)]);
      setFailures(outcome.failed);
      setResult(`${fmt.int(outcome.succeeded.length)} مورد موفق، ${fmt.int(outcome.failed.length)} مورد ناموفق، ${fmt.int(skipped.length)} مورد نامرتبط. برای تلاش دوباره، جزئیات خطا و وضعیت موارد انتخاب‌شده را بررسی کنید.`);
      onComplete();
    } finally { setBusy(false); onBusy(false); setPending(null); }
  }
  const visible = selected.length > 0 || busy || result !== null;
  return <>
    {visible ? <div className="fixed inset-x-3 bottom-4 z-40 mx-auto flex max-w-3xl flex-wrap items-center gap-2 rounded-lg border border-[color:var(--line)] bg-white p-3 shadow-xl sm:gap-3" dir="rtl" aria-busy={busy}>
      {selected.length > 0 ? <span className="text-sm font-medium">{fmt.int(selected.length)} مورد انتخاب شده</span> : null}
      {actions.map((action) => {
        const count = selected.filter(action.eligible).length;
        if (count === 0) return null;
        return <button key={action.label} type="button" className={action.destructive ? "btn text-rose-600" : "btn"}
          disabled={disabled || busy} onClick={() => action.destructive ? setPending(action) : void run(action)}>
          {action.label} ({fmt.int(count)})
        </button>;
      })}
      <span className="flex-1" />
      {selected.length > 0 ? <button type="button" className="btn-ghost" disabled={busy} onClick={() => { setSelected([]); setResult(null); setFailures([]); }}>لغو انتخاب</button> : null}
      {selected.length === 0 && !busy ? <button type="button" className="btn-ghost" onClick={() => { setResult(null); setFailures([]); }}>بستن</button> : null}
      <span role="status" className="w-full text-sm">{busy ? `در حال انجام… ${fmt.int(progress)} مورد` : result}</span>
      {failures.length > 0 ? <details className="w-full max-h-40 overflow-auto text-sm text-rose-700"><summary>جزئیات موارد ناموفق</summary><ul>{failures.map((failure) => <li key={failure.id}><bdi>{failure.id}</bdi>: {failure.message}</li>)}</ul></details> : null}
    </div> : null}
    <ConfirmDialog open={pending !== null} title="حذف گروهی" description={`${fmt.int(pending ? selected.filter(pending.eligible).length : 0)} مورد به همراه فایل صوتی، متن و تحلیل‌های مرتبط برای همیشه حذف می‌شوند. این عملیات قابل بازگشت نیست.`}
      confirmLabel="حذف موارد انتخاب‌شده" destructive busy={busy} onCancel={() => setPending(null)} onConfirm={() => { if (pending) void run(pending); }} />
  </>;
}
