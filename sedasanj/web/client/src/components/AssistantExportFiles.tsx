import { useCallback, useRef, useState, type ReactNode } from "react";
import { ApiError, downloadFile } from "../api";
import FileTypeIcon from "./FileTypeIcon";
import Toast from "./Toast";
import type { AssistantExportFile } from "../types";
import { exportDownloadPath } from "./assistantExportLinks.mjs";

export function ExportFileLink({ file, children }: { file: AssistantExportFile; children?: ReactNode }) {
  const downloading = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const closeToast = useCallback(() => setError(null), []);
  const expiredMessage = "مهلت دریافت فایل تمام شده است؛ از دستیار خروجی جدید بخواهید.";

  async function download() {
    if (downloading.current) return;
    const deadline = Date.parse(file.expires_at);
    if (!Number.isFinite(deadline) || Date.now() >= deadline) {
      setError(expiredMessage);
      return;
    }
    downloading.current = true;
    setBusy(true);
    setError(null);
    try {
      await downloadFile(exportDownloadPath(file), file.name);
    } catch (cause) {
      setError(cause instanceof ApiError && cause.code === "export_expired"
        ? expiredMessage
        : "دریافت فایل انجام نشد؛ دوباره تلاش کنید.");
    } finally {
      downloading.current = false;
      setBusy(false);
    }
  }

  return <span className="inline" dir="rtl">
    <a
      href={exportDownloadPath(file)}
      onClick={(event) => { event.preventDefault(); void download(); }}
      aria-disabled={busy}
      aria-busy={busy}
      className={`inline-flex max-w-full items-baseline gap-1 align-baseline text-[#4B6E48] underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-current ${busy ? "cursor-not-allowed opacity-50" : "hover:text-[#365033]"}`}
    >
      <span className="self-center"><FileTypeIcon name={file.name} format={file.format} size={16} /></span>
      <span className="min-w-0 break-words">{children || <>دریافت <bdi dir="ltr">{file.name}</bdi></>}</span>
    </a>
    {busy ? <span role="status" className="mr-2 text-xs">در حال دریافت…</span> : null}
    {error ? <Toast message={error} onClose={closeToast} /> : null}
  </span>;
}
