import { useEffect, useMemo, useState } from "react";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import type { PublicPlan } from "../types";

export default function Checkout() {
  const [params] = useSearchParams();
  const [plans, setPlans] = useState<PublicPlan[]>([]);
  const [period, setPeriod] = useState<"monthly" | "annual">("monthly");
  const [extra, setExtra] = useState(0);
  const [form, setForm] = useState({ name: "", email: "", mobile: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const code = params.get("plan") ?? "bronze";
  const plan = plans.find((item) => item.code === code);

  useEffect(() => {
    request<PublicPlan[]>("/v1/plans").then(setPlans).catch((reason) => setError(reason.message));
  }, []);

  const total = useMemo(() => {
    if (!plan) return 0;
    const base = period === "annual" ? plan.annual_price_toman ?? 0 : plan.monthly_price_toman;
    const unit = period === "annual" ? plan.extra_operator_annual_toman ?? 0 : plan.extra_operator_monthly_toman ?? 0;
    return base + unit * extra;
  }, [plan, period, extra]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!plan) return;
    if (!termsAccepted) {
      setError("برای ادامه، قوانین، حریم خصوصی و سیاست لغو را بپذیرید.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const order = await request<{ id: string }>("/v1/orders", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: {
          plan_code: plan.code,
          billing_period: period,
          extra_operators: extra,
          customer_name: form.name,
          customer_email: form.email,
          customer_mobile: form.mobile,
          invoice_profile: {},
          terms_accepted: termsAccepted,
        },
      });
      const payment = await request<{ redirect_url: string }>(`/v1/orders/${order.id}/pay`, { method: "POST" });
      window.location.assign(payment.redirect_url);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "ساخت سفارش انجام نشد.");
      setBusy(false);
    }
  }

  if (!plan) return <div className="card">{error || "در حال دریافت اطلاعات پلن…"}</div>;
  return <div className="commerce-page"><div className="commerce-heading"><span>خرید اشتراک</span><h1>پلن {plan.name}</h1><p>مبلغ نهایی در سرور محاسبه می‌شود و قیمت نمایش‌داده‌شده شامل مالیات است.</p></div>
    {error ? <div className="commerce-error">{error}</div> : null}
    <div className="commerce-grid"><form className="card commerce-form" onSubmit={submit}>
      <div className="period-switch"><button type="button" className={period === "monthly" ? "active" : ""} onClick={() => setPeriod("monthly")}>ماهانه</button><button type="button" className={period === "annual" ? "active" : ""} onClick={() => setPeriod("annual")}>سالانه · ۲ ماه تخفیف</button></div>
      {plan.allows_extra_operators ? <label>اپراتور اضافه<input type="number" min={0} max={500} value={extra} onChange={(event) => setExtra(Number(event.target.value))} /></label> : null}
      <label>نام خریدار<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
      <label>ایمیل<input type="email" dir="ltr" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
      <label>موبایل<input type="tel" dir="ltr" required value={form.mobile} onChange={(event) => setForm({ ...form, mobile: fmt.latinDigits(event.target.value) })} /></label>
      <ToggleSwitch className="terms-check" checked={termsAccepted} onChange={setTermsAccepted} label="قوانین، حریم خصوصی و سیاست لغو را می‌پذیرم." />
      <button className="btn" disabled={busy}>{busy ? "در حال انتقال…" : "پرداخت امن"}</button>
    </form><aside className="card order-summary"><h2>خلاصه سفارش</h2><div><span>اشتراک {period === "annual" ? "سالانه" : "ماهانه"}</span><strong>{fmt.toman(period === "annual" ? plan.annual_price_toman ?? 0 : plan.monthly_price_toman)}</strong></div>{extra ? <div><span>{fmt.int(extra)} اپراتور اضافه</span><strong>{fmt.toman(total - (period === "annual" ? plan.annual_price_toman ?? 0 : plan.monthly_price_toman))}</strong></div> : null}<hr/><div className="summary-total"><span>مبلغ نهایی</span><strong>{fmt.toman(total)}</strong></div></aside></div>
  </div>;
}
