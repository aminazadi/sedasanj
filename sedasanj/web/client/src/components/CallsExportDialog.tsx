import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useEffect, useState } from "react";
import { downloadFile, query } from "../api";
import FormDialog from "./FormDialog";
import exportArt from "../assets/calls-export.svg";

export interface CallsExportFilters {
  from: string;
  to: string;
  q: string;
  intent: string;
  sentiment: string;
  number: string;
  status: string;
  direction: string;
}

interface ExportColumn {
  key: string;
  label: string;
  /** Hidden from operators, who never see billing data. */
  billing?: boolean;
  defaultOn: boolean;
}

// Keys and order mirror COLUMNS in apps/api/app/services/call_export.py.
export const EXPORT_COLUMNS: ExportColumn[] = [
  { key: "started_at", label: "زمان شروع", defaultOn: true },
  { key: "ended_at", label: "زمان پایان", defaultOn: false },
  { key: "caller_number", label: "شمارهٔ تماس‌گیرنده", defaultOn: true },
  { key: "caller_name", label: "نام تماس‌گیرنده", defaultOn: true },
  { key: "dialed_number", label: "شمارهٔ مقصد", defaultOn: true },
  { key: "dialed_name", label: "نام مقصد", defaultOn: false },
  { key: "direction", label: "جهت تماس", defaultOn: true },
  { key: "agent_extension", label: "داخلی", defaultOn: false },
  { key: "duration", label: "مدت تماس", defaultOn: true },
  { key: "billed_seconds", label: "ثانیهٔ محاسبه‌شده", billing: true, defaultOn: false },
  { key: "call_type", label: "نوع تماس", defaultOn: true },
  { key: "intent", label: "قصد", defaultOn: true },
  { key: "sentiment", label: "احساس", defaultOn: true },
  { key: "sentiment_trajectory", label: "روند احساس", defaultOn: false },
  { key: "summary", label: "خلاصه", defaultOn: true },
];

const STORAGE_KEY = "calls-export-columns";

function initialSelection(operator: boolean): string[] {
  const allowed = EXPORT_COLUMNS.filter((column) => !(operator && column.billing)).map((column) => column.key);
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null") as unknown;
    if (Array.isArray(saved)) {
      const kept = saved.filter((key): key is string => typeof key === "string" && allowed.includes(key));
      if (kept.length) return kept;
    }
  } catch {
    // Storage unavailable or corrupt: fall back to the defaults.
  }
  return EXPORT_COLUMNS.filter((column) => column.defaultOn && allowed.includes(column.key)).map((column) => column.key);
}

export default function CallsExportDialog({ open, filters, operator, onClose }: { open: boolean; filters: CallsExportFilters; operator: boolean; onClose: () => void }) {
  const [selected, setSelected] = useState<string[]>(() => initialSelection(operator));
  const [format, setFormat] = useState<"xlsx" | "csv">("xlsx");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const columns = EXPORT_COLUMNS.filter((column) => !(operator && column.billing));

  useEffect(() => {
    if (open) {
      setSelected(initialSelection(operator));
      setError(null);
    }
  }, [open, operator]);

  function toggle(key: string) {
    setSelected((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selected));
      } catch {
        // Remembering the choice is a convenience only.
      }
      const params = query({ ...filters, columns: selected.join(","), format });
      await downloadFile(`/v1/calls/export${params}`, `calls.${format}`);
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const hasFilters = Object.values(filters).some(Boolean);

  return (
    <FormDialog
      open={open}
      wide
      art={exportArt}
      title="خروجی گرفتن از تماس‌ها"
      description={hasFilters ? "فقط تماس‌هایی که با جست‌وجو و فیلترهای فعلی همخوانی دارند در خروجی قرار می‌گیرند." : "همهٔ تماس‌های قابل مشاهدهٔ شما در خروجی قرار می‌گیرند."}
      submitLabel="دریافت خروجی"
      submitDisabled={selected.length === 0}
      busy={busy}
      error={error}
      onClose={onClose}
      onSubmit={() => void submit()}
    >
      <fieldset className="demo-field">
        <legend>ستون‌های خروجی</legend>
        <div className="mb-2 mt-2 flex gap-4 text-xs">
          <button type="button" className="underline" onClick={() => setSelected(columns.map((column) => column.key))}>انتخاب همه</button>
          <button type="button" className="underline" onClick={() => setSelected([])}>حذف همه</button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {columns.map((column) => (
            <ToggleSwitch key={column.key} checked={selected.includes(column.key)} onChange={() => toggle(column.key)} label={column.label} labelClassName="text-sm" />
          ))}
        </div>
      </fieldset>
      <label>
        <span>قالب فایل</span>
        <select value={format} onChange={(event) => setFormat(event.target.value as "xlsx" | "csv")}>
          <option value="xlsx">اکسل (XLSX)</option>
          <option value="csv">CSV (سازگار با اکسل)</option>
        </select>
      </label>
      <p>تاریخ‌ها شمسی و به وقت تهران هستند و حداکثر ۲۰٬۰۰۰ تماس در هر خروجی قرار می‌گیرد.</p>
    </FormDialog>
  );
}
