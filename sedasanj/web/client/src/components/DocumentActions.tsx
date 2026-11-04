import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { downloadFile } from "../api";
import { safeDownloadName } from "../utils/download";
import { ErrorBox } from "./Widgets";
import "./document-print.css";

type DocumentActionsProps = {
  path: string;
  title: string;
  kind: string;
  metadata: Array<[string, string]>;
  children: ReactNode;
};

export default function DocumentActions({ path, title, kind, metadata, children }: DocumentActionsProps) {
  const [printing, setPrinting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!printing) return;
    const originalTitle = document.title;
    document.title = title;
    document.body.classList.add("document-print-active");
    let canceled = false;
    const finish = () => setPrinting(false);
    window.addEventListener("afterprint", finish);
    void document.fonts.ready.then(() => {
      // Give the print layout and its SVG charts a frame to measure their containers.
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (canceled) return;
        try {
          window.print();
        } catch {
          setError("پیش‌نمایش چاپ باز نشد. دوباره تلاش کنید یا PDF را دانلود کنید.");
          finish();
        }
      }));
    });
    return () => {
      canceled = true;
      document.title = originalTitle;
      document.body.classList.remove("document-print-active");
      window.removeEventListener("afterprint", finish);
    };
  }, [printing, title]);

  async function download() {
    setError("");
    setDownloading(true);
    try {
      await downloadFile(path, `${safeDownloadName(title, "sedasanj")}.pdf`);
    } catch (err) {
      setError(err instanceof Error && err.message && !(err instanceof TypeError)
        ? err.message
        : "دریافت PDF ممکن نشد. اتصال را بررسی کنید و دوباره تلاش کنید.");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap gap-2">
        <button className="btn h-9 px-3 py-0 text-xs" type="button" disabled={downloading} onClick={() => void download()}>
          {downloading ? "در حال دریافت PDF…" : "دانلود PDF"}
        </button>
        <button className="btn-ghost h-9 px-3 py-0 text-xs" type="button" disabled={printing} onClick={() => { setError(""); setPrinting(true); }}>
          چاپ
        </button>
      </div>
      {error ? <div className="mt-2"><ErrorBox message={error} /></div> : null}
      {printing ? createPortal(
        <article className="document-print" dir="rtl" lang="fa">
          <header className="document-print-brand">
            <span>صداسنج</span>
            <span className="document-print-mark" aria-hidden="true"><i /><i /><i /></span>
          </header>
          <h1>{title}</h1>
          <p className="document-print-kind">{kind}</p>
          <dl>
            {metadata.map(([label, value]) => <div key={label}><dt>{label}</dt><dd dir="auto">{value}</dd></div>)}
          </dl>
          <div className="document-print-content">{children}</div>
        </article>,
        document.body,
      ) : null}
    </div>
  );
}
