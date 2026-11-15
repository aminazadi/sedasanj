import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, fmt, request } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";

const BASE = "/v1/admin/jalase/achievements";

type Metric = "meetings" | "documents" | "categories" | "streak_weeks";
type Achievement = {
  id: string; code: string; title_fa: string; description_fa: string; metric: Metric;
  threshold: number; reward_tokens: number; sort_order: number; active: boolean;
};
type Draft = { title_fa: string; description_fa: string; threshold: number; reward_tokens: number; sort_order: number };

const METRICS: Record<Metric, string> = {
  meetings: "تعداد جلسه‌ها",
  documents: "تعداد سندهای ساخته‌شده",
  categories: "تعداد دسته‌های متفاوت",
  streak_weeks: "هفته‌های پیاپی دارای جلسه",
};
const EMPTY = { code: "", title_fa: "", description_fa: "", metric: "meetings" as Metric, threshold: 1, reward_tokens: 5000, sort_order: 100 };

const message = (reason: unknown) =>
  reason instanceof ApiError ? reason.message : "ارتباط با سامانه برقرار نشد. اتصال را بررسی و دوباره تلاش کنید.";

export default function JalaseAchievements() {
  const [items, setItems] = useState<Achievement[] | null>(null);
  const [editing, setEditing] = useState<{ id: string; draft: Draft } | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try { setItems(await request<Achievement[]>(BASE)); setError(null); }
    catch (reason) { setError(message(reason)); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  async function run(action: () => Promise<unknown>, done: string) {
    if (busy) return;
    setBusy(true); setError(null); setNotice("");
    try { await action(); setNotice(done); await reload(); }
    catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  }

  const create = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      await request(BASE, { method: "POST", retry: false, body: form });
      setForm(EMPTY);
    }, "نشان ساخته شد.");
  };
  const patch = (id: string, body: Record<string, unknown>, done: string) =>
    run(async () => { await request(`${BASE}/${id}`, { method: "PATCH", body }); setEditing(null); }, done);

  if (!items) return <div className="space-y-4"><ErrorBox message={error} /><Loading /></div>;
  return <div className="space-y-4">
    <div>
      <h1 className="text-2xl font-bold">نشان‌های جلسه‌نگار</h1>
      <p className="mt-1 text-sm text-slate-500">رسیدن به هر نشان، مقداری توکن هدیه می‌دهد (۶۰ روز اعتبار). مجموع هدیهٔ نشان‌ها در هر ماه به درصدی از سهمیهٔ پلن محدود است؛ این درصد و توکن دعوت دوستان در تنظیمات مدل‌ها هستند. نشانی که کاربر گرفته با تغییر مقدار هدیه دوباره پرداخت نمی‌شود.</p>
    </div>
    <ErrorBox message={error} />
    {notice ? <div className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-700">{notice}</div> : null}
    <form className="card grid gap-3 md:grid-cols-4" onSubmit={create}>
      <label><span className="label">کد (انگلیسی)</span><input className="input" dir="ltr" required pattern="[a-z0-9_]{2,48}" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></label>
      <label><span className="label">عنوان</span><input className="input" required minLength={2} maxLength={80} value={form.title_fa} onChange={(e) => setForm({ ...form, title_fa: e.target.value })} /></label>
      <label className="md:col-span-2"><span className="label">توضیح</span><input className="input" required minLength={2} maxLength={300} value={form.description_fa} onChange={(e) => setForm({ ...form, description_fa: e.target.value })} /></label>
      <label><span className="label">معیار</span><select className="input" value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value as Metric })}>{(Object.keys(METRICS) as Metric[]).map((key) => <option key={key} value={key}>{METRICS[key]}</option>)}</select></label>
      <label><span className="label">حد لازم</span><input className="input" type="number" min={1} required value={form.threshold} onChange={(e) => setForm({ ...form, threshold: Number(fmt.latinDigits(e.target.value)) })} /></label>
      <label><span className="label">توکن هدیه</span><input className="input" type="number" min={0} required value={form.reward_tokens} onChange={(e) => setForm({ ...form, reward_tokens: Number(fmt.latinDigits(e.target.value)) })} /></label>
      <div className="flex items-end"><button className="btn" disabled={busy}>افزودن نشان</button></div>
    </form>
    <div className="card overflow-x-auto">
      <table className="table"><thead><tr><th>نشان</th><th>معیار</th><th>حد لازم</th><th>توکن هدیه</th><th>وضعیت</th><th /></tr></thead>
        <tbody>{items.map((item) => {
          const draft = editing?.id === item.id ? editing.draft : null;
          const setDraft = (next: Draft) => setEditing({ id: item.id, draft: next });
          return <tr key={item.id}>
            <td>{draft
              ? <div className="space-y-1"><input className="input" value={draft.title_fa} onChange={(e) => setDraft({ ...draft, title_fa: e.target.value })} /><input className="input" value={draft.description_fa} onChange={(e) => setDraft({ ...draft, description_fa: e.target.value })} /></div>
              : <>{item.title_fa}<small className="block text-slate-500">{item.description_fa}</small><small className="block text-slate-400" dir="ltr">{item.code}</small></>}</td>
            <td>{METRICS[item.metric]}</td>
            <td>{draft ? <input className="input w-24" type="number" min={1} value={draft.threshold} onChange={(e) => setDraft({ ...draft, threshold: Number(fmt.latinDigits(e.target.value)) })} /> : fmt.int(item.threshold)}</td>
            <td>{draft ? <input className="input w-28" type="number" min={0} value={draft.reward_tokens} onChange={(e) => setDraft({ ...draft, reward_tokens: Number(fmt.latinDigits(e.target.value)) })} /> : fmt.int(item.reward_tokens)}</td>
            <td>{item.active ? <span className="badge bg-emerald-50 text-emerald-700">فعال</span> : <span className="badge bg-slate-100 text-slate-500">غیرفعال</span>}</td>
            <td className="space-x-2 space-x-reverse">
              {draft
                ? <><button className="btn-ghost text-xs" disabled={busy} onClick={() => void patch(item.id, draft, "نشان ذخیره شد.")}>ذخیره</button><button className="btn-ghost text-xs" onClick={() => setEditing(null)}>انصراف</button></>
                : <button className="btn-ghost text-xs" onClick={() => setDraft({ title_fa: item.title_fa, description_fa: item.description_fa, threshold: item.threshold, reward_tokens: item.reward_tokens, sort_order: item.sort_order })}>ویرایش</button>}
              <button className="btn-ghost text-xs" disabled={busy} onClick={() => void patch(item.id, { active: !item.active }, item.active ? "نشان غیرفعال شد." : "نشان فعال شد.")}>{item.active ? "غیرفعال‌سازی" : "فعال‌سازی"}</button>
            </td>
          </tr>;
        })}</tbody></table>
    </div>
  </div>;
}
