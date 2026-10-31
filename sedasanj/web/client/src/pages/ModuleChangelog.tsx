import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ReleaseTimeline, { type ReleaseEntry } from "@cbi/web-shared/components/ReleaseTimeline";
import { ErrorBox, Loading } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
import { loadReleases, sanitizeHtml } from "../moduleUpdates";

export default function ModuleChangelog() {
  const [params, setParams] = useSearchParams();
  const product = params.get("product") === "issabel-recuploader" ? "issabel-recuploader" : "freepbx-recuploader";
  const [entries, setEntries] = useState<ReleaseEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEntries(null);
    loadReleases(product)
      .then((page) => setEntries(page.items))
      .catch((err) => setError((err as Error).message));
  }, [product]);

  return (
    <div className="space-y-4">
      <PageHeader title="تغییرات نسخه‌های ماژول مرکز تلفن" description="هر نسخهٔ جدید در صفحهٔ «Seda Sanj» پنل مرکز تلفن شما با یک دکمه نصب می‌شود؛ پیش از نصب، فایل امضا و یک نسخهٔ پشتیبان گرفته می‌شود." />
      <ErrorBox message={error} />
      <select className="input" aria-label="نوع مرکز تلفن" value={product} onChange={(event) => setParams({ product: event.target.value })}>
        <option value="freepbx-recuploader">FreePBX</option><option value="issabel-recuploader">ایزابل</option>
      </select>
      <section className="card">
        {entries === null && !error ? <Loading /> : <ReleaseTimeline entries={entries ?? []} sanitize={sanitizeHtml} />}
      </section>
    </div>
  );
}
