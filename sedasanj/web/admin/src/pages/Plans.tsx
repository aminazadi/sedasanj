import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { ApiError, fmt, request } from "../api";
import { useReasonDialog } from "../components/ReasonDialog";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import { toOffset, useUrlParams } from "../lib/useUrlParams";
import type { Page, PlanVersion } from "../types";

interface VersionForm {
  annual_price_toman: number;
  base_operators: number;
  intro_minutes: number;
  overage_price_per_minute_toman: number;
  assistant_tier: string;
  assistant_monthly_messages: number;
  assistant_source_limit: number;
  assistant_model: string;
  allows_extra_operators: boolean;
  extra_operator_annual_toman: number;
  trial_days: number;
}

const EMPTY_VERSION: VersionForm = {
  annual_price_toman: 0,
  base_operators: 1,
  intro_minutes: 0,
  overage_price_per_minute_toman: 7000,
  assistant_tier: "simple",
  assistant_monthly_messages: 50,
  assistant_source_limit: 8,
  assistant_model: "",
  allows_extra_operators: false,
  extra_operator_annual_toman: 0,
  trial_days: 7,
};

const NUMBER_FIELDS = [
  ["annual_price_toman", "قیمت سالانه"],
  ["base_operators", "اپراتور پایه"],
  ["intro_minutes", "دقیقه رایگان ماهانه"],
  ["overage_price_per_minute_toman", "تعرفه هر دقیقه"],
  ["assistant_monthly_messages", "پیام دستیار ماهانه"],
  ["assistant_source_limit", "حد منابع"],
  ["trial_days", "روز آزمایشی"],
] as const;

const STATUS_LABELS = { draft: "پیش‌نویس", published: "منتشرشده", retired: "بازنشسته" } as const;

/** Starting values for a new draft: the plan's newest version, so only what changes is edited. */
function formFrom(rows: PlanVersion[]): VersionForm {
  const latest = rows.filter((row) => row.id).sort((a, b) => (b.version ?? 0) - (a.version ?? 0))[0];
  if (!latest) return EMPTY_VERSION;
  return {
    annual_price_toman: latest.annual_price_toman ?? 0,
    base_operators: latest.base_operators ?? 1,
    intro_minutes: latest.intro_minutes ?? 0,
    overage_price_per_minute_toman: latest.overage_price_per_minute_toman ?? 7000,
    assistant_tier: latest.assistant_tier ?? "simple",
    assistant_monthly_messages: latest.assistant_monthly_messages ?? 0,
    assistant_source_limit: latest.assistant_source_limit ?? 8,
    assistant_model: latest.assistant_model ?? "",
    allows_extra_operators: latest.allows_extra_operators ?? false,
    extra_operator_annual_toman: latest.extra_operator_annual_toman ?? 0,
    trial_days: latest.trial_days ?? 7,
  };
}

function validate(form: VersionForm, trial: boolean, sellable: boolean): string | null {
  for (const [key, label] of NUMBER_FIELDS) {
    const value = form[key];
    if (!Number.isInteger(value) || value < 0) return `«${label}» باید عدد صحیح و نامنفی باشد.`;
  }
  if (form.base_operators < 1) return "حداقل یک اپراتور پایه لازم است.";
  if (form.assistant_source_limit < 1 || form.assistant_source_limit > 200) return "حد منابع باید بین ۱ و ۲۰۰ باشد.";
  if (sellable && !trial && form.annual_price_toman <= 0) return "پلن قابل‌فروش به قیمت سالانه بیشتر از صفر نیاز دارد.";
  if (trial && (form.trial_days < 1 || form.trial_days > 90)) return "روز آزمایشی باید بین ۱ و ۹۰ باشد.";
  return null;
}

export default function Plans() {
  const limit = 25;
  const [filters, setFilters] = useUrlParams({ offset: "0", plan: "" });
  const offset = toOffset(filters.offset);
  const [form, setForm] = useState<VersionForm>(EMPTY_VERSION);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [planForm, setPlanForm] = useState({ code: "", name: "", public: true, sellable: true, is_trial: false, sort_order: 0 });
  const [ask, dialog] = useReasonDialog();
  const plans = useResource<Page<PlanVersion>>(
    (signal) => request<Page<PlanVersion>>(`/v1/admin/commerce/plans?limit=${limit}&cursor=${offset}`, { signal }),
    [offset],
  );
  const rows = plans.data?.items ?? [];
  const codes = useMemo(() => Array.from(new Set(rows.map((item) => item.code))), [rows]);
  const selected = filters.plan && codes.includes(filters.plan) ? filters.plan : (codes[0] ?? "");
  const selectedRows = rows.filter((row) => row.code === selected);
  const selectedPlan = selectedRows[0];

  useEffect(() => {
    if (selected) setForm(formFrom(rows.filter((row) => row.code === selected)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, plans.data]);

  async function run(action: () => Promise<unknown>, done: string) {
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      plans.reload();
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  async function createVersion(event: React.FormEvent) {
    event.preventDefault();
    const problem = validate(form, selectedPlan?.is_trial ?? false, selectedPlan?.sellable ?? true);
    if (problem) {
      setError(problem);
      return;
    }
    await run(
      () =>
        request(`/v1/admin/commerce/plans/${selected}/versions`, {
          method: "POST",
          body: {
            ...form,
            assistant_model: form.assistant_model || null,
            extra_operator_annual_toman: form.allows_extra_operators ? form.extra_operator_annual_toman : null,
            trial_days: selectedPlan?.is_trial ? form.trial_days : null,
          },
        }),
      "نسخه پیش‌نویس ساخته شد.",
    );
  }

  async function createPlan(event: React.FormEvent) {
    event.preventDefault();
    await run(async () => {
      await request("/v1/admin/commerce/plans", { method: "POST", body: planForm });
      setPlanForm({ code: "", name: "", public: true, sellable: true, is_trial: false, sort_order: 0 });
    }, "پلن ساخته شد؛ اکنون نسخه پیش‌نویس آن را بسازید.");
  }

  async function updatePlan(item: PlanVersion, changes: Record<string, unknown>, message: string) {
    const result = await ask(message);
    if (!result) return;
    await run(
      () => request(`/v1/admin/commerce/plans/${item.code}`, { method: "PATCH", body: { ...changes, reason: result.reason } }),
      "پلن به‌روز شد.",
    );
  }

  async function publish(item: PlanVersion) {
    const result = await ask(`انتشار نسخه ${fmt.int(item.version ?? 0)} پلن ${item.name}؛ نسخه منتشرشدهٔ قبلی بازنشسته می‌شود و مشترکان فعلی روی نسخهٔ خودشان می‌مانند.`, { confirmLabel: "انتشار" });
    if (!result) return;
    await run(() => request(`/v1/admin/commerce/plan-versions/${item.id}/publish`, { method: "POST", body: { reason: result.reason } }), "نسخه منتشر شد.");
  }

  async function retire(item: PlanVersion) {
    const result = await ask(`بازنشسته‌کردن نسخه ${fmt.int(item.version ?? 0)} پلن ${item.name}؛ ${fmt.int(item.subscription_count)} اشتراک به این نسخه وصل است و تا پایان دوره‌شان ادامه می‌دهند.`, { confirmLabel: "بازنشسته", destructive: true });
    if (!result) return;
    const send = (force: boolean) => request(`/v1/admin/commerce/plan-versions/${item.id}/retire`, { method: "POST", body: { reason: result.reason, force } });
    await run(async () => {
      try {
        await send(false);
      } catch (reason) {
        if (reason instanceof ApiError && reason.code === "plan_in_use" && window.confirm("این تنها نسخهٔ منتشرشدهٔ پلن فعال است و پس از بازنشستگی پلن قابل خرید نمی‌ماند. ادامه می‌دهید؟")) {
          await send(true);
          return;
        }
        throw reason;
      }
    }, "نسخه بازنشسته شد.");
  }

  if (plans.error && !plans.data) return <ErrorBox message={plans.error} />;
  if (!plans.data) return <Loading />;
  return <div className="space-y-5">
    {dialog}
    <div><h1 className="text-2xl font-bold">پلن‌ها و نسخه‌ها</h1><p className="mt-1 text-sm text-slate-500">نسخه‌های منتشرشده تغییر نمی‌کنند؛ تغییرات ابتدا به‌صورت پیش‌نویس ساخته می‌شوند.</p></div>
    <ErrorBox message={error ?? plans.error} />
    {notice ? <div className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-700">{notice}</div> : null}
    <form className="card grid gap-3 md:grid-cols-4" onSubmit={createPlan}>
      <input className="input" dir="ltr" placeholder="کد پلن" pattern="[a-z0-9_]{2,32}" value={planForm.code} onChange={(event) => setPlanForm({ ...planForm, code: event.target.value })} required />
      <input className="input" placeholder="نام پلن" value={planForm.name} onChange={(event) => setPlanForm({ ...planForm, name: event.target.value })} required />
      <input className="input" inputMode="numeric" placeholder="ترتیب نمایش" value={fmt.digits(planForm.sort_order)} onChange={(event) => setPlanForm({ ...planForm, sort_order: Number(fmt.latinDigits(event.target.value)) || 0 })} />
      <button className="btn">ایجاد پلن</button>
      <ToggleSwitch checked={planForm.public} onChange={(checked) => setPlanForm({ ...planForm, public: checked })} label="نمایش عمومی" labelClassName="text-sm" />
      <ToggleSwitch checked={planForm.sellable} disabled={planForm.is_trial} onChange={(checked) => setPlanForm({ ...planForm, sellable: checked })} label="قابل خرید" labelClassName="text-sm" />
      <ToggleSwitch checked={planForm.is_trial} onChange={(checked) => setPlanForm({ ...planForm, is_trial: checked, sellable: checked ? false : planForm.sellable })} label="پلن آزمایشی" labelClassName="text-sm" />
    </form>
    <form className="card space-y-4" onSubmit={createVersion}>
      <div className="flex flex-wrap items-end gap-3"><div><label className="label">پلن</label><select className="input min-w-40" value={selected} onChange={(event) => setFilters({ plan: event.target.value })}>{codes.map((code) => <option key={code}>{code}</option>)}</select></div><button className="btn" disabled={!selected}>ساخت نسخه پیش‌نویس</button><p className="text-xs text-slate-500">مقادیر از آخرین نسخهٔ این پلن آمده‌اند.</p></div>
      <div className="grid gap-3 md:grid-cols-4">
        {NUMBER_FIELDS.filter(([key]) => key !== "trial_days" || selectedPlan?.is_trial).map(([key, label]) => <div key={key}><label className="label">{label}</label><input className="input" inputMode="numeric" value={fmt.digits(form[key])} onChange={(event) => setForm({ ...form, [key]: Number(fmt.latinDigits(event.target.value)) })} /></div>)}
        <div><label className="label">سطح دستیار</label><input className="input" dir="ltr" value={form.assistant_tier} onChange={(event) => setForm({ ...form, assistant_tier: event.target.value })} /></div>
        <div><label className="label">مدل اختصاصی دستیار</label><input className="input" dir="ltr" value={form.assistant_model} onChange={(event) => setForm({ ...form, assistant_model: event.target.value })} /></div>
        <ToggleSwitch checked={form.allows_extra_operators} onChange={(checked) => setForm({ ...form, allows_extra_operators: checked })} label="اپراتور اضافه مجاز است" labelClassName="text-sm" />
        {form.allows_extra_operators ? <div><label className="label">اپراتور اضافه سالانه</label><input className="input" inputMode="numeric" value={fmt.digits(form.extra_operator_annual_toman)} onChange={(event) => setForm({ ...form, extra_operator_annual_toman: Number(fmt.latinDigits(event.target.value)) })} /></div> : null}
      </div>
    </form>
    <div className="card overflow-x-auto">{rows.length === 0 ? <Empty /> : <table className="table"><thead><tr><th>پلن</th><th>نسخه</th><th>وضعیت</th><th>سالانه</th><th>دقیقه رایگان / ماه</th><th>تعرفه دقیقه</th><th>پیام دستیار / ماه</th><th>اپراتور</th><th>آزمایشی</th><th>اشتراک</th><th>عملیات</th></tr></thead><tbody>{rows.map((item) => <tr key={item.id ?? `plan-${item.plan_id}`}>
      <td>{item.name}<small className="block text-slate-400" dir="ltr">{item.code}</small><small className="block text-slate-500">{item.is_trial ? "آزمایشی" : item.sellable ? "قابل خرید" : "غیرقابل خرید"}{item.public ? "" : " · خصوصی"}{item.active ? "" : " · غیرفعال"}</small></td>
      {item.id ? <>
        <td>{fmt.int(item.version ?? 0)}{item.effective_at ? <small className="block text-slate-400">از {fmt.date(item.effective_at)}</small> : null}</td>
        <td>{item.status ? STATUS_LABELS[item.status] : "—"}</td>
        <td>{fmt.toman(item.annual_price_toman ?? 0)}{item.allows_extra_operators ? <small className="block text-slate-400">اپراتور اضافه {fmt.toman(item.extra_operator_annual_toman ?? 0)}</small> : null}</td>
        <td>{fmt.int(item.intro_minutes ?? 0)}</td><td>{fmt.toman(item.overage_price_per_minute_toman ?? 0)}</td><td>{fmt.int(item.assistant_monthly_messages ?? 0)}<small className="block text-slate-400" dir="ltr">{item.assistant_tier}{item.assistant_model ? ` / ${item.assistant_model}` : ""}</small></td><td>{fmt.int(item.base_operators ?? 0)}</td><td>{item.trial_days ? `${fmt.int(item.trial_days)} روز` : "—"}</td>
        <td><Link className="text-brand-600" to={`/subscriptions?plan=${encodeURIComponent(item.code)}`}>{fmt.int(item.subscription_count)}</Link></td>
      </> : <td colSpan={9} className="text-slate-500">این پلن هنوز نسخه‌ای ندارد؛ از بالا «ساخت نسخه پیش‌نویس» را بزنید.</td>}
      <td className="space-x-2 space-x-reverse">{item.status === "draft" ? <button className="btn-ghost text-xs" onClick={() => void publish(item)}>انتشار</button> : null}{item.status === "published" ? <button className="btn-ghost text-xs text-rose-700" onClick={() => void retire(item)}>بازنشسته</button> : null}<button className="btn-ghost text-xs" onClick={() => void updatePlan(item, { public: !item.public }, item.public ? "پلن از صفحهٔ عمومی پنهان می‌شود." : "پلن در صفحهٔ عمومی نمایش داده می‌شود.")}>{item.public ? "خصوصی‌کردن" : "عمومی‌کردن"}</button><button className="btn-ghost text-xs" onClick={() => void updatePlan(item, { active: !item.active }, item.active ? `توقف فروش پلن ${item.name}؛ ${fmt.int(item.subscription_count)} اشتراک این نسخه فعال است.` : "پلن دوباره فعال می‌شود.")}>{item.active ? "توقف فروش" : "فعال‌سازی فروش"}</button></td></tr>)}</tbody></table>}</div>
    <Pagination offset={offset} limit={limit} total={plans.data.total} onChange={(next) => setFilters({ offset: String(next) })} />
  </div>;
}
