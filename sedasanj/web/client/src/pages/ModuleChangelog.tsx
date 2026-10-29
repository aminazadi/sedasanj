import { useEffect, useState } from "react";
import ReleaseTimeline, { type ReleaseEntry } from "@cbi/web-shared/components/ReleaseTimeline";
import { ErrorBox, Loading } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
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
      <PageHeader title="تغییرات نسخه‌های ماژول FreePBX" description="هر نسخهٔ جدید در صفحهٔ «Seda Sanj» پنل FreePBX شما با یک دکمه نصب می‌شود؛ پیش از نصب، فایل امضا و یک نسخهٔ پشتیبان گرفته می‌شود." />
      <ErrorBox message={error} />
      <section className="card">
        {entries === null && !error ? <Loading /> : <ReleaseTimeline entries={entries ?? []} sanitize={sanitizeHtml} />}
      </section>
    </div>
  );
}
