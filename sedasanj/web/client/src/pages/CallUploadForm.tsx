import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { CAN_UPLOAD_CALLS, isOperator, useAuth } from "../auth";
import { ErrorBox } from "../components/Widgets";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import type { User } from "../types";

interface UploadAccepted {
  call_id: string;
  status: string;
}

const EMPTY = {
  caller: "",
  dialed: "",
  uniqueid: "",
  startedAt: "",
  endedAt: "",
  direction: "inbound",
  extension: "",
};

export default function CallUploadForm({ onUploaded }: { onUploaded: () => void }) {
  const { session } = useAuth();
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function close() {
    if (busy) return;
    setOpen(false);
    setFile(null);
    setForm(EMPTY);
    setError(null);
    setNotice(null);
  }

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, busy]);

  useEffect(() => {
    if (!open || !isOperator(session?.role)) return;
    void request<User>("/v1/auth/me")
      .then((me) => {
        setForm((current) => ({
          ...current,
          extension: current.extension || me.extension || "",
        }));
      })
      .catch(() => undefined);
  }, [open, session?.role]);

  if (!session || !CAN_UPLOAD_CALLS.includes(session.role)) return null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setError("یک فایل WAV انتخاب کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("caller_number", form.caller.trim());
      body.append("dialed_number", form.dialed.trim());
      body.append("direction", form.direction);
      if (form.uniqueid.trim()) body.append("asterisk_uniqueid", form.uniqueid.trim());
      if (form.startedAt) body.append("started_at", new Date(form.startedAt).toISOString());
      if (form.endedAt) body.append("ended_at", new Date(form.endedAt).toISOString());
      if (form.extension.trim()) body.append("agent_extension", form.extension.trim());
      const result = await request<UploadAccepted>("/v1/calls/upload", { method: "POST", body });
      setNotice(
        result.status === "queued"
          ? "فایل در صف پیاده‌سازی قرار گرفت. در فهرست تماس‌ها مرحله و درصد پیشرفت را می‌بینید."
          : "این شناسه قبلاً ثبت شده بود؛ تماس تکراری ساخته نشد.",
      );
      setFile(null);
      setForm(EMPTY);
      onUploaded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="btn" onClick={() => setOpen(true)}>
        آپلود دستی
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 sm:items-center"
          onClick={close}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="upload-modal-title"
            className="max-h-[calc(100dvh-2rem)] w-full max-w-2xl overflow-y-auto rounded-xl border border-slate-200 bg-white p-5 shadow-xl sm:max-h-none sm:overflow-visible"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 id="upload-modal-title" className="text-lg font-bold">
                  آپلود دستی مکالمه
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  مسیر اصلی همچنان ایجنت روی سانترال است. این فرم برای بازیابی یا تست است.
                </p>
              </div>
              <button type="button" className="btn-ghost text-sm" onClick={close} disabled={busy}>
                بستن
              </button>
            </div>
            <form className="grid gap-3 md:grid-cols-2" onSubmit={(event) => void submit(event)}>
              <div className="md:col-span-2">
                <ErrorBox message={error} />
                {notice ? (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
                    {notice}
                  </div>
                ) : null}
              </div>
              <p className="md:col-span-2 text-sm text-slate-600">
                فقط WAV خطی ۸ یا ۱۶ کیلوهرتز. در فایل استریو کانال چپ مشتری و کانال راست اپراتور است.
                اگر زمان را خالی بگذارید از مدت فایل استفاده می‌شود.
              </p>
              <div className="md:col-span-2">
                <label className="label">فایل WAV</label>
                <input
                  className="input"
                  type="file"
                  accept=".wav,audio/wav"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  required
                />
              </div>
              <div>
                <label className="label">شماره تماس‌گیرنده</label>
                <input
                  className="input"
                  dir="ltr"
                  value={fmt.digits(form.caller)}
                  onChange={(event) => setForm({ ...form, caller: fmt.latinDigits(event.target.value) })}
                  required
                />
              </div>
              <div>
                <label className="label">شماره مقصد</label>
                <input
                  className="input"
                  dir="ltr"
                  value={fmt.digits(form.dialed)}
                  onChange={(event) => setForm({ ...form, dialed: fmt.latinDigits(event.target.value) })}
                  required
                />
              </div>
              <div>
                <label className="label">جهت</label>
                <select
                  className="input"
                  value={form.direction}
                  onChange={(event) => setForm({ ...form, direction: event.target.value })}
                >
                  <option value="inbound">ورودی</option>
                  <option value="outbound">خروجی</option>
                  <option value="internal">داخلی</option>
                </select>
              </div>
              <div>
                <label className="label">داخلی اپراتور (اختیاری)</label>
                <input
                  className="input"
                  dir="ltr"
                  value={fmt.digits(form.extension)}
                  onChange={(event) => setForm({ ...form, extension: fmt.latinDigits(event.target.value) })}
                />
              </div>
              <div>
                <label className="label">شروع (اختیاری)</label>
                <JalaliDatePicker
                  value={form.startedAt}
                  onChange={(startedAt) => setForm({ ...form, startedAt })}
                  includeTime
                  placeholder="انتخاب تاریخ و ساعت شروع"
                />
              </div>
              <div>
                <label className="label">پایان (اختیاری)</label>
                <JalaliDatePicker
                  value={form.endedAt}
                  onChange={(endedAt) => setForm({ ...form, endedAt })}
                  includeTime
                  placeholder="انتخاب تاریخ و ساعت پایان"
                />
              </div>
              <div className="md:col-span-2">
                <label className="label">شناسه یکتا (اختیاری)</label>
                <input
                  className="input"
                  dir="ltr"
                  placeholder="خالی بماند تا خودکار ساخته شود"
                  value={fmt.digits(form.uniqueid)}
                  onChange={(event) => setForm({ ...form, uniqueid: fmt.latinDigits(event.target.value) })}
                />
              </div>
              <div className="md:col-span-2 flex justify-end gap-2">
                <button type="button" className="btn-ghost" onClick={close} disabled={busy}>
                  انصراف
                </button>
                <button className="btn" disabled={busy}>
                  {busy ? "در حال ارسال…" : "ارسال برای تحلیل"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
