import { useState } from "react";
import { request } from "../api";
import { Empty, ErrorBox } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
import { useResource } from "@cbi/web-shared/lib/useResource";

interface MenuEntry { code: string; label: string; hidden?: boolean }
interface MenuResponse { items: MenuEntry[]; hidden: string[] }

/** Org admins choose which Jalase-Negar document categories show in the panel menu. */
export default function JalaseMenu() {
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const menu = useResource<MenuResponse>((signal) => request<MenuResponse>("/v1/jalase/org-menu", { signal }), [version]);

  async function toggle(code: string, hidden: boolean) {
    setBusy(code);
    setError(null);
    try {
      await request(`/v1/jalase/org-menu/${encodeURIComponent(code)}/hidden`, { method: "PUT", body: JSON.stringify({ hidden }) });
      setVersion((current) => current + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const visible = menu.data?.items ?? [];
  const hidden = menu.data?.hidden ?? [];
  return (
    <div className="space-y-4">
      <PageHeader title="منوی جلسه‌نگار" description="دسته‌هایی که سازمان شما در آن‌ها سند دارد؛ هر دسته‌ای که مخفی کنید از منوی کناری حذف می‌شود و اسناد آن پاک نمی‌شوند." />
      <ErrorBox message={error ?? menu.error ?? null} />
      {visible.length === 0 && hidden.length === 0 ? <Empty>هنوز سندی در دسته‌های جلسه‌نگار ثبت نشده است. پس از ارسال اولین سند از اپ، دسته‌اش اینجا ظاهر می‌شود.</Empty> : null}
      <ul className="space-y-2">
        {visible.map((entry) => (
          <li key={entry.code} className="card flex items-center justify-between gap-3">
            <span>{entry.label}</span>
            <button type="button" className="btn btn-ghost" disabled={busy === entry.code} onClick={() => toggle(entry.code, true)}>مخفی کردن</button>
          </li>
        ))}
        {hidden.map((code) => (
          <li key={code} className="card flex items-center justify-between gap-3">
            <span className="text-slate-500">{code} (مخفی)</span>
            <button type="button" className="btn btn-ghost" disabled={busy === code} onClick={() => toggle(code, false)}>نمایش دوباره</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
