import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { renderDocumentPdf } from "../lib/documentPdf";
import { safeDownloadName } from "../utils/download";
import DocumentHeader from "./DocumentHeader";
import DocumentActionIcon, { DOCUMENT_ACTION_CLASS } from "./DocumentActionIcon";
import { ErrorBox } from "./Widgets";
import "./document-print.css";

type DocumentActionsProps = {
  title: string;
  kind: string;
  metadata: Array<[string, string]>;
  children: ReactNode;
  disabled?: boolean;
  contentKey: string;
  iconOnly?: boolean;
};

export default function DocumentActions({ title, kind, metadata, children, disabled, contentKey, iconOnly = false }: DocumentActionsProps) {
  const [mode, setMode] = useState<"print" | "download" | "share" | null>(null);
  const [error, setError] = useState("");
  const [shareFile, setShareFile] = useState<File | null>(null);
  const documentRef = useRef<HTMLElement>(null);
  useEffect(() => { setShareFile(null); }, [contentKey, title]);

  useEffect(() => {
    if (!mode) return;
    let canceled = false;
    const originalTitle = document.title;
    const finish = () => setMode(null);
    async function prepare() {
      await document.fonts.ready;
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      if (canceled || !documentRef.current) return;
      try {
        if (mode === "print") {
          document.title = title;
          document.body.classList.add("document-print-active");
          window.print();
          return;
        }
        const blob = await renderDocumentPdf(documentRef.current);
        if (canceled) return;
        const file = new File([blob], `${safeDownloadName(title, "sedasanj")}.pdf`, { type: "application/pdf" });
        if (mode === "share" && navigator.canShare?.({ files: [file] })) {
          setShareFile(file);
        } else {
          const url = URL.createObjectURL(file);
          const link = document.createElement("a");
          link.href = url; link.download = file.name; link.click();
          window.setTimeout(() => URL.revokeObjectURL(url), 60000);
          if (mode === "share") setError("اشتراک مستقیم فایل در این مرورگر در دسترس نیست؛ فایل PDF دانلود شد و می‌توانید آن را ارسال کنید.");
        }
        finish();
      } catch {
        setError("خروجی سند ساخته نشد؛ دوباره تلاش کنید یا از گزینه چاپ استفاده کنید. (document_pdf_unavailable)");
        finish();
      }
    }
    window.addEventListener("afterprint", finish);
    void prepare();
    return () => {
      canceled = true;
      document.title = originalTitle;
      document.body.classList.remove("document-print-active");
      window.removeEventListener("afterprint", finish);
    };
  }, [mode, title]);

  async function share() {
    setError("");
    if (!shareFile) { setMode("share"); return; }
    try { await navigator.share({ title, files: [shareFile] }); }
    catch (err) { if (!(err instanceof DOMException && err.name === "AbortError")) setError("اشتراک‌گذاری انجام نشد؛ دوباره تلاش کنید یا PDF را دانلود و ارسال کنید."); }
  }

  return <div className="min-w-0">
    <div className="flex flex-wrap gap-2">
      <button className={iconOnly ? DOCUMENT_ACTION_CLASS : "btn h-9 whitespace-nowrap px-3 py-0 text-xs"} aria-label="دانلود PDF" title="دانلود PDF" aria-busy={mode === "download"} type="button" disabled={!!mode || disabled} onClick={() => { setError(""); setMode("download"); }}>{iconOnly ? <DocumentActionIcon name="download" busy={mode === "download"} /> : mode === "download" ? "در حال ساخت PDF…" : "دانلود PDF"}</button>
      <button className={iconOnly ? DOCUMENT_ACTION_CLASS : "btn-ghost h-9 whitespace-nowrap px-3 py-0 text-xs"} aria-label="چاپ" title="چاپ" aria-busy={mode === "print"} type="button" disabled={!!mode || disabled} onClick={() => { setError(""); setMode("print"); }}>{iconOnly ? <DocumentActionIcon name="print" busy={mode === "print"} /> : "چاپ"}</button>
      <button className={iconOnly ? DOCUMENT_ACTION_CLASS : "btn-ghost h-9 whitespace-nowrap px-3 py-0 text-xs"} aria-label={shareFile ? "ارسال فایل PDF" : "اشتراک‌گذاری"} title={shareFile ? "ارسال فایل PDF" : "اشتراک‌گذاری"} aria-busy={mode === "share"} type="button" disabled={!!mode || disabled} onClick={() => void share()}>{iconOnly ? <DocumentActionIcon name="share" busy={mode === "share"} /> : mode === "share" ? "در حال آماده‌سازی…" : shareFile ? "ارسال فایل PDF" : "اشتراک‌گذاری"}</button>
    </div>
    {error ? <div className="mt-2 max-w-md"><ErrorBox message={error} /></div> : null}
    {mode ? createPortal(<div className="document-export-host">
      <article ref={documentRef} className="document-print" dir="rtl" lang="fa" aria-label={kind}>
        <DocumentHeader title={title} actions={null} metadata={metadata.map(([label, value]) => <span key={label}>{label}: <bdi>{value}</bdi></span>)} />
        <div className="document-body document-print-content">{children}</div>
      </article>
    </div>, document.body) : null}
  </div>;
}
