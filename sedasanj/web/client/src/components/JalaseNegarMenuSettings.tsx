import { useState } from "react";
import { request } from "../api";
import { Empty, ErrorBox } from "./Widgets";
import { useResource } from "@cbi/web-shared/lib/useResource";

interface MenuEntry { code: string; label: string; hidden?: boolean }
interface MenuResponse { items: MenuEntry[]; hidden: string[]; categories: MenuEntry[] }

/** Org admins choose which Jalase-Negar document categories show in the panel's "جلسه‌نگار" menu group. */
export default function JalaseNegarMenuSettings() {
  const [version, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const menu = useResource<MenuResponse>((signal) => request<MenuResponse>("/v1/jalase/org-menu", { signal }), [version]);

  async function toggle(code: string, hidden: boolean) {
    setBusy(code);
    setError(null);
    try {
      await request(`/v1/jalase/org-menu/${encodeURIComponent(code)}/hidden`, { method: "PUT", body: { hidden } });
      setVersion((current) => current + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const categories = menu.data?.categories ?? [];
  return (
    <section className="card space-y-4" aria-labelledby="jalase-negar-menu-title">
      <div>
        <h2 id="jalase-negar-menu-title" className="font-bold">منوی جلسه‌نگار</h2>
        <p className="section-hint">همهٔ دسته‌های جلسه‌نگار؛ هر دسته‌ای که مخفی کنید از گروه «جلسه‌نگار» در منوی کناری حذف می‌شود و اسناد آن پاک نمی‌شوند.</p>
      </div>
      <ErrorBox message={error ?? menu.error ?? null} />
      {!menu.loading && categories.length === 0 ? <Empty>هنوز دسته‌ای برای جلسه‌نگار منتشر نشده است.</Empty> : null}
      <ul className="space-y-2">
        {categories.map((entry) => (
          <li key={entry.code} className="card flex items-center justify-between gap-3">
            <span className={entry.hidden ? "text-slate-500" : undefined}>{entry.label}{entry.hidden ? " (مخفی)" : ""}</span>
            <button type="button" className="btn-ghost h-9 px-3 py-0 text-xs" disabled={busy === entry.code} onClick={() => toggle(entry.code, !entry.hidden)}>{entry.hidden ? "نمایش دوباره" : "مخفی کردن"}</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
