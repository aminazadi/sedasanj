import { useCallback, useEffect, useState } from "react";
import { request } from "../api";
import { Empty, ErrorBox, Loading } from "../components/Widgets";
import type { HelpCategory } from "../types";

interface Draft {
  id: string | null;
  slug: string;
  title: string;
  description: string;
  position: string;
}

const BLANK: Draft = { id: null, slug: "", title: "", description: "", position: "0" };

export default function HelpCategories() {
  const [items, setItems] = useState<HelpCategory[] | null>(null);
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setItems(await request<HelpCategory[]>("/v1/admin/help/categories"));
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const body = {
        slug: draft.slug.trim().toLowerCase(),
        title: draft.title.trim(),
        description: draft.description.trim(),
        position: Number(draft.position) || 0,
      };
      if (draft.id) {
        await request(`/v1/admin/help/categories/${draft.id}`, { method: "PUT", body });
      } else {
        await request("/v1/admin/help/categories", { method: "POST", body });
      }
      setDraft(BLANK);
      await reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(category: HelpCategory) {
    if (!window.confirm(`دستهٔ «${category.title}» حذف شود؟ مقاله‌های آن بدون دسته می‌مانند.`)) return;
    try {
      await request(`/v1/admin/help/categories/${category.id}`, { method: "DELETE" });
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-extrabold text-slate-900">دسته‌های راهنما</h1>
        <p className="text-sm text-slate-500">مثلاً «نصب»، «خطاهای آپلود»، «به‌روزرسانی».</p>
      </div>
      <ErrorBox message={error} />
      <div className="card grid gap-3 sm:grid-cols-4">
        <div>
          <label className="label">عنوان</label>
          <input className="input" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
        </div>
        <div>
          <label className="label">نشانی (slug)</label>
          <input className="input" dir="ltr" value={draft.slug} onChange={(e) => setDraft({ ...draft, slug: e.target.value.toLowerCase() })} />
        </div>
        <div>
          <label className="label">ترتیب</label>
          <input className="input" dir="ltr" inputMode="numeric" value={draft.position} onChange={(e) => setDraft({ ...draft, position: e.target.value })} />
        </div>
        <div className="flex items-end gap-2">
          <button type="button" className="btn" disabled={busy} onClick={() => void save()}>
            {draft.id ? "ذخیرهٔ تغییر" : "افزودن دسته"}
          </button>
          {draft.id ? (
            <button type="button" className="btn btn-ghost" onClick={() => setDraft(BLANK)}>
              انصراف
            </button>
          ) : null}
        </div>
        <div className="sm:col-span-4">
          <label className="label">توضیح کوتاه</label>
          <input className="input" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
        </div>
      </div>
      {items === null ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty>هنوز دسته‌ای نیست.</Empty>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="table">
            <thead>
              <tr>
                <th>عنوان</th>
                <th>نشانی</th>
                <th>مقاله‌ها</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td className="font-bold">{c.title}</td>
                  <td dir="ltr" className="text-xs text-slate-500">
                    {c.slug}
                  </td>
                  <td>{c.article_count}</td>
                  <td className="flex gap-2">
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setDraft({ id: c.id, slug: c.slug, title: c.title, description: c.description, position: String(c.position) })
                      }
                    >
                      ویرایش
                    </button>
                    <button type="button" className="btn btn-ghost btn-sm text-rose-600" onClick={() => void remove(c)}>
                      حذف
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
