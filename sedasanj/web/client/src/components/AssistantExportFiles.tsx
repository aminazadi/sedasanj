import { useEffect, useState } from "react";
import { ApiError, downloadFile, fmt } from "../api";
import type { AssistantExportFile, AssistantToolRun } from "../types";

export function exportFiles(runs: AssistantToolRun[]): AssistantExportFile[] {
  return [...new Map(runs.flatMap((run) => run.files || []).map((file) => [file.export_id, file])).values()];
}

export function ExportFileCard({ file }: { file: AssistantExportFile }) {
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [gone, setGone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deadline = Date.parse(file.expires_at);
  const expired = gone || !Number.isFinite(deadline) || now >= deadline;
  const minutes = Math.max(0, Math.ceil((deadline - now) / 60000));

  useEffect(() => {
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [file.export_id]);

  async function download() {
    if (busy || expired) return;
    if (Date.now() >= deadline) { setNow(Date.now()); return; }
    setBusy(true);
    setError(null);
    try {
      await downloadFile(`/v1/assistant/exports/${encodeURIComponent(file.export_id)}/download`, file.name);
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === "export_expired") setGone(true);
      setError(cause instanceof Error ? cause.message : "دریافت فایل انجام نشد؛ دوباره تلاش کنید");
    } finally {
      setBusy(false);
    }
  }

  return <div className="my-3 border border-[#B2AC88] bg-white p-3 text-[#365033]" dir="rtl">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <p className="break-all text-sm" dir="ltr">{file.name}</p>
        <p className="text-xs"><bdi dir="ltr">{file.format.toUpperCase()}</bdi> · {fmt.int(file.size / 1024)} کیلوبایت · {fmt.int(file.rows)} ردیف</p>
        <p className="text-xs" title={fmt.dateTime(file.expires_at)}>{expired ? "منقضی شد؛ از دستیار خروجی جدید بخواهید" : `تا ${fmt.int(minutes)} دقیقه دیگر معتبر است؛ سپس حذف می‌شود`}</p>
      </div>
      <button type="button" onClick={() => void download()} disabled={expired || busy} className="inline-flex items-center gap-2 border border-[#B2AC88] px-3 py-2 text-sm transition hover:bg-[#F2F0EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:opacity-50" aria-label={`دریافت ${file.name}`}>
        <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></svg>
        {expired ? "منقضی شد" : busy ? "در حال دریافت…" : "دریافت فایل"}
      </button>
    </div>
    {error ? <p role="alert" className="mt-2 text-xs text-rose-700">{error}</p> : null}
  </div>;
}

export default function AssistantExportFiles({ runs }: { runs: AssistantToolRun[] }) {
  return <>{exportFiles(runs).map((file) => <ExportFileCard key={file.export_id} file={file} />)}</>;
}
