import { useEffect, useMemo, useState } from "react";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import type { PublicPlan } from "../types";
import { BrandLogo } from "../components/BrandLogo";
import planDemoImage from "../assets/plan-demo.png";
import planBronzeImage from "../assets/plan-bronze.png";
import planSilverImage from "../assets/plan-silver.png";
import planGoldImage from "../assets/plan-gold.png";

const planImages: Record<string, string> = { demo: planDemoImage, bronze: planBronzeImage, silver: planSilverImage, gold: planGoldImage };

export default function Checkout() {
  const [params] = useSearchParams();
  const [plans, setPlans] = useState<PublicPlan[]>([]);
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
    const base = plan.annual_price_toman ?? 0;
    const unit = plan.extra_operator_annual_toman ?? 0;
    return base + unit * extra;
  }, [plan, extra]);

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
          billing_period: "annual",
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

  if (!plan) return <main className="checkout-shell" dir="rtl"><div className="checkout-page"><div className="checkout-brand"><Link to="/" aria-label="صفحه اصلی"><BrandLogo animated className="block w-48 sm:w-56" title="صداسنج" /></Link></div><section className="checkout-panel"><p className={error ? "commerce-error" : "checkout-loading"}>{error || "در حال دریافت اطلاعات پلن…"}</p></section></div></main>;
  return <main className="checkout-shell" dir="rtl"><div className="checkout-page"><div className="checkout-brand"><Link to="/" aria-label="صفحه اصلی"><BrandLogo animated className="block w-48 sm:w-56" title="صداسنج" /></Link></div><section className="checkout-panel"><div className="checkout-plan-intro"><img className="checkout-plan-art" src={planImages[plan.code] ?? planImages.bronze} alt={`تصویر پلن ${plan.name}`} /><header className="checkout-heading"><span>خرید و ارتقای پلن {plan.name}</span><h1>پلن خود را فعال کنید</h1><p>اطلاعات پرداخت را تکمیل کنید.</p></header></div>
    {error ? <div className="commerce-error">{error}</div> : null}
    <div className="checkout-summary"><div><span>اشتراک سالانه</span><strong>{fmt.toman(plan.annual_price_toman ?? 0)}</strong></div>{extra ? <div><span>{fmt.int(extra)} اپراتور اضافه</span><strong>{fmt.toman(total - (plan.annual_price_toman ?? 0))}</strong></div> : null}<div className="checkout-total"><span>مبلغ نهایی</span><strong>{fmt.toman(total)}</strong></div></div><form className="commerce-form checkout-form" onSubmit={submit}>
      <p className="text-sm text-slate-500">دوره پرداخت اشتراک: سالانه</p>
      {plan.allows_extra_operators ? <label>اپراتور اضافه<input type="number" min={0} max={500} value={extra} onChange={(event) => setExtra(Number(event.target.value))} /></label> : null}
      <label>نام خریدار<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
      <label>ایمیل<input type="email" dir="ltr" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
      <label>موبایل<input type="tel" dir="ltr" required value={form.mobile} onChange={(event) => setForm({ ...form, mobile: fmt.latinDigits(event.target.value) })} /></label>
      <ToggleSwitch className="terms-check" checked={termsAccepted} onChange={setTermsAccepted} label="قوانین، حریم خصوصی و سیاست لغو را می‌پذیرم." />
      <button className="btn" disabled={busy}>{busy ? "در حال انتقال…" : "پرداخت امن"}</button>
    </form><p className="checkout-back"><Link to="/plans">بازگشت به پلن‌ها</Link></p></section></div></main>;
}
