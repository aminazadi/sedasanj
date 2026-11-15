import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, request } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";

const BASE = "/v1/admin/jalase/store-skus";

type Store = "bazaar" | "myket";
type Item = { id: string; store: Store; sku: string; kind: "plan" | "pack"; plan_code: string | null; package_id: string | null; active: boolean };
type Listing = { items: Item[]; plans: { code: string; name: string }[]; packs: { id: string; name: string; tokens: number }[] };

const STORES: Record<Store, string> = { bazaar: "کافه‌بازار", myket: "مایکت" };

const message = (reason: unknown) =>
  reason instanceof ApiError ? reason.message : "ارتباط با سامانه برقرار نشد. اتصال را بررسی و دوباره تلاش کنید.";

export default function JalaseStoreSkus() {
  const [data, setData] = useState<Listing | null>(null);
  const [store, setStore] = useState<Store>("bazaar");
  const [sku, setSku] = useState("");
  const [target, setTarget] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try { setData(await request<Listing>(BASE)); setError(null); }
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
    const [kind, value] = target.split(":");
    void run(async () => {
      await request(BASE, { method: "POST", retry: false, body: { store, sku: sku.trim(), ...(kind === "plan" ? { plan_code: value } : { package_id: value }) } });
      setSku("");
    }, "محصول ثبت شد.");
  };

  if (!data) return <div className="space-y-4"><ErrorBox message={error} /><Loading /></div>;
  const label = (item: Item) => item.kind === "plan"
    ? `پلن ${data.plans.find((plan) => plan.code === item.plan_code)?.name ?? item.plan_code}`
    : `بستهٔ ${data.packs.find((pack) => pack.id === item.package_id)?.name ?? "توکن"}`;
  return <div className="space-y-4">
    <div>
      <h1 className="text-2xl font-bold">محصولات مارکت جلسه‌نگار</h1>
      <p className="mt-1 text-sm text-slate-500">شناسهٔ محصولی که در پنل کافه‌بازار یا مایکت ساخته‌اید را به یک پلن ماهانه یا یک بستهٔ توکن وصل کنید. محصول در مارکت باید «یک‌بار مصرف» (مصرف‌شدنی) باشد. بدون این فهرست، خرید درون‌برنامه‌ای در نسخهٔ مارکت کار نمی‌کند.</p>
    </div>
    <ErrorBox message={error} />
    {notice ? <div className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-700">{notice}</div> : null}
    <form className="card grid gap-3 md:grid-cols-4" onSubmit={create}>
      <label><span className="label">مارکت</span><select className="input" value={store} onChange={(e) => setStore(e.target.value as Store)}>{(Object.keys(STORES) as Store[]).map((key) => <option key={key} value={key}>{STORES[key]}</option>)}</select></label>
      <label><span className="label">شناسهٔ محصول (SKU)</span><input className="input" dir="ltr" required pattern="[A-Za-z0-9_.\-]{1,64}" value={sku} onChange={(e) => setSku(e.target.value)} /></label>
      <label><span className="label">می‌فروشد</span><select className="input" required value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="">انتخاب کنید</option>
        {data.plans.map((plan) => <option key={plan.code} value={`plan:${plan.code}`}>پلن {plan.name}</option>)}
        {data.packs.map((pack) => <option key={pack.id} value={`pack:${pack.id}`}>بستهٔ {pack.name}</option>)}
      </select></label>
      <div className="flex items-end"><button className="btn" disabled={busy || !target}>افزودن محصول</button></div>
    </form>
    <div className="card overflow-x-auto">
      <table className="table"><thead><tr><th>مارکت</th><th>SKU</th><th>می‌فروشد</th><th>وضعیت</th><th /></tr></thead>
        <tbody>{data.items.map((item) => <tr key={item.id}>
          <td>{STORES[item.store]}</td>
          <td dir="ltr">{item.sku}</td>
          <td>{label(item)}</td>
          <td>{item.active ? <span className="badge bg-emerald-50 text-emerald-700">فعال</span> : <span className="badge bg-slate-100 text-slate-500">غیرفعال</span>}</td>
          <td><button className="btn-ghost text-xs" disabled={busy} onClick={() => void run(() => request(`${BASE}/${item.id}`, { method: "PATCH", body: { active: !item.active } }), item.active ? "محصول غیرفعال شد." : "محصول فعال شد.")}>{item.active ? "غیرفعال‌سازی" : "فعال‌سازی"}</button></td>
        </tr>)}</tbody></table>
      {data.items.length === 0 ? <p className="p-4 text-sm text-slate-500">هنوز محصولی ثبت نشده است.</p> : null}
    </div>
  </div>;
}
