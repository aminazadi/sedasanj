import { useEffect, useState } from "react";
import ReleaseTimeline, { type ReleaseEntry } from "@cbi/web-shared/components/ReleaseTimeline";
import { ErrorBox } from "../components/Widgets";
import { loadReleases, sanitizeHtml } from "../moduleUpdates";

export default function ModuleChangelog() {
  const [entries, setEntries] = useState<ReleaseEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadReleases()
      .then((page) => setEntries(page.items))
      .catch((err) => setError((err as Error).message));
  }, []);

  return (
    <div className="space-y-4">
      <section className="card">
        <h1 className="text-xl font-extrabold text-slate-900">تغییرات نسخه‌های ماژول FreePBX</h1>
        <p className="mt-1 text-sm text-slate-500">
          هر نسخهٔ جدید در صفحهٔ «Seda Sanj» پنل FreePBX شما با یک دکمه نصب می‌شود؛ پیش از نصب، فایل امضا و یک نسخهٔ پشتیبان گرفته می‌شود.
        </p>
      </section>
      <ErrorBox message={error} />
      <section className="card">
        {entries === null && !error ? (
          <div className="py-10 text-center text-slate-400">در حال بارگذاری…</div>
        ) : (
          <ReleaseTimeline entries={entries ?? []} sanitize={sanitizeHtml} />
        )}
      </section>
    </div>
  );
}
