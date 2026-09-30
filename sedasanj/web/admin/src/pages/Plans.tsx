import { useEffect, useMemo, useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Page, PlanVersion } from "../types";

const EMPTY_VERSION = {
  monthly_price_toman: 0,
  annual_price_toman: 0,
  base_operators: 1,
  intro_minutes: 0,
  overage_price_per_minute_toman: 2000,
  assistant_tier: "simple",
  assistant_monthly_messages: 50,
  assistant_source_limit: 8,
  assistant_model: "",
  allows_extra_operators: false,
  extra_operator_monthly_toman: 0,
  extra_operator_annual_toman: 0,
  trial_days: 7,
};

export default function Plans() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [versions, setVersions] = useState<PlanVersion[] | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [form, setForm] = useState(EMPTY_VERSION);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [planForm, setPlanForm] = useState({code: "", name: "", public: true, sort_order: 0});

  async function reload() {
    try {
      const page = await request<Page<PlanVersion>>(`/v1/admin/commerce/plans?limit=${limit}&cursor=${offset}`);
      setVersions(page.items);
      setTotal(page.total);
      if (!selected && page.items.length) setSelected(page.items[0].code);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  useEffect(() => { void reload(); }, [offset]);
  const codes = useMemo(() => Array.from(new Set((versions ?? []).map((item) => item.code))), [versions]);

  async function createVersion(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await request(`/v1/admin/commerce/plans/${selected}/versions`, {
        method: "POST",
        body: {
          ...form,
          annual_price_toman: form.annual_price_toman || null,
          assistant_model: form.assistant_model || null,
          extra_operator_monthly_toman: form.allows_extra_operators ? form.extra_operator_monthly_toman : null,
          extra_operator_annual_toman: form.allows_extra_operators ? form.extra_operator_annual_toman : null,
          trial_days: form.trial_days || null,
        },
      });
      setNotice("نسخه پیش‌نویس ساخته شد.");
      await reload();
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  async function createPlan(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await request("/v1/admin/commerce/plans", {method: "POST", body: planForm});
      setPlanForm({code: "", name: "", public: true, sort_order: 0});
      setNotice("پلن ساخته شد؛ اکنون نسخه پیش‌نویس آن را بسازید.");
      await reload();
    } catch (reason) { setError((reason as Error).message); }
  }

  async function updatePlan(item: PlanVersion, changes: Record<string, unknown>) {
    try {
      await request(`/v1/admin/commerce/plans/${item.code}`, {method: "PATCH", body: changes});
      await reload();
    } catch (reason) { setError((reason as Error).message); }
  }

  if (!versions) return <Loading />;
  return <div className="space-y-5">
    <div><h1 className="text-2xl font-bold">پلن‌ها و نسخه‌ها</h1><p className="mt-1 text-sm text-slate-500">نسخه‌های منتشرشده تغییر نمی‌کنند؛ تغییرات ابتدا به‌صورت پیش‌نویس ساخته می‌شوند.</p></div>
    <ErrorBox message={error} />
    {notice ? <div className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-700">{notice}</div> : null}
    <form className="card grid gap-3 md:grid-cols-5" onSubmit={createPlan}>
      <input className="input" dir="ltr" placeholder="کد پلن" pattern="[a-z0-9_]{2,32}" value={planForm.code} onChange={(event) => setPlanForm({...planForm, code: event.target.value})} required />
      <input className="input" placeholder="نام پلن" value={planForm.name} onChange={(event) => setPlanForm({...planForm, name: event.target.value})} required />
      <input className="input" inputMode="numeric" placeholder="ترتیب نمایش" value={fmt.digits(planForm.sort_order)} onChange={(event) => setPlanForm({...planForm, sort_order: Number(fmt.latinDigits(event.target.value))})} />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={planForm.public} onChange={(event) => setPlanForm({...planForm, public: event.target.checked})} />نمایش عمومی</label>
      <button className="btn">ایجاد پلن</button>
    </form>
    <form className="card space-y-4" onSubmit={createVersion}>
      <div className="flex flex-wrap items-end gap-3"><div><label className="label">پلن</label><select className="input min-w-40" value={selected} onChange={(event) => setSelected(event.target.value)}>{codes.map((code) => <option key={code}>{code}</option>)}</select></div><button className="btn" disabled={!selected}>ساخت نسخه پیش‌نویس</button></div>
      <div className="grid gap-3 md:grid-cols-4">
        {([['monthly_price_toman','قیمت ماهانه'],['annual_price_toman','قیمت سالانه'],['base_operators','اپراتور پایه'],['intro_minutes','دقیقه هدیه'],['overage_price_per_minute_toman','نرخ دقیقه اضافه'],['assistant_monthly_messages','پیام دستیار'],['assistant_source_limit','حد منابع'],['trial_days','روز آزمایشی']] as const).map(([key, label]) => <div key={key}><label className="label">{label}</label><input className="input" inputMode="numeric" value={fmt.digits(form[key])} onChange={(event) => setForm({...form, [key]: Number(fmt.latinDigits(event.target.value))})}/></div>)}
        <div><label className="label">سطح دستیار</label><input className="input" dir="ltr" value={form.assistant_tier} onChange={(event) => setForm({...form, assistant_tier: event.target.value})}/></div>
        <div><label className="label">مدل اختصاصی دستیار</label><input className="input" dir="ltr" value={form.assistant_model} onChange={(event) => setForm({...form, assistant_model: event.target.value})}/></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.allows_extra_operators} onChange={(event) => setForm({...form, allows_extra_operators: event.target.checked})}/>اپراتور اضافه مجاز است</label>
        {form.allows_extra_operators ? <><div><label className="label">اپراتور اضافه ماهانه</label><input className="input" inputMode="numeric" value={fmt.digits(form.extra_operator_monthly_toman)} onChange={(event) => setForm({...form, extra_operator_monthly_toman: Number(fmt.latinDigits(event.target.value))})}/></div><div><label className="label">اپراتور اضافه سالانه</label><input className="input" inputMode="numeric" value={fmt.digits(form.extra_operator_annual_toman)} onChange={(event) => setForm({...form, extra_operator_annual_toman: Number(fmt.latinDigits(event.target.value))})}/></div></> : null}
      </div>
    </form>
    <div className="card overflow-x-auto">{versions.length === 0 ? <Empty /> : <table className="table"><thead><tr><th>پلن</th><th>نسخه</th><th>وضعیت</th><th>ماهانه</th><th>سالانه</th><th>اپراتور</th><th>اشتراک</th><th>عملیات</th></tr></thead><tbody>{versions.map((item) => <tr key={item.id}><td>{item.name}<small className="block text-slate-400" dir="ltr">{item.code}</small></td><td>{fmt.int(item.version)}</td><td>{item.status === 'draft' ? 'پیش‌نویس' : item.status === 'published' ? 'منتشرشده' : 'بازنشسته'}</td><td>{fmt.toman(item.monthly_price_toman)}</td><td>{item.annual_price_toman == null ? '—' : fmt.toman(item.annual_price_toman)}</td><td>{fmt.int(item.base_operators)}</td><td>{fmt.int(item.subscription_count)}</td><td className="space-x-2 space-x-reverse">{item.status === 'draft' ? <button className="btn-ghost text-xs" onClick={async () => { const reason = window.prompt('دلیل انتشار را وارد کنید'); if (!reason) return; await request(`/v1/admin/commerce/plan-versions/${item.id}/publish`, {method:'POST', body:{reason}}); await reload(); }}>انتشار</button> : null}{item.status === 'published' ? <button className="btn-ghost text-xs text-rose-700" onClick={async () => { const reason = window.prompt('دلیل بازنشستگی را وارد کنید'); if (!reason) return; await request(`/v1/admin/commerce/plan-versions/${item.id}/retire`, {method:'POST', body:{reason}}); await reload(); }}>بازنشسته</button> : null}<button className="btn-ghost text-xs" onClick={() => void updatePlan(item, {public: !item.public})}>{item.public ? 'خصوصی‌کردن' : 'عمومی‌کردن'}</button><button className="btn-ghost text-xs" onClick={() => void updatePlan(item, {active: !item.active})}>{item.active ? 'توقف فروش' : 'فعال‌سازی فروش'}</button></td></tr>)}</tbody></table>}</div>
    <Pagination offset={offset} limit={limit} total={total} onChange={setOffset} />
  </div>;
}
