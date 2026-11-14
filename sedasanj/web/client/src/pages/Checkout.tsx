import { useEffect, useMemo, useRef, useState } from "react";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import PaymentMethodPicker from "../components/PaymentMethodPicker";
import { billingErrorMessage } from "../lib/billingErrors.mjs";
import { startPayment, type GatewayCode } from "../lib/payment";
import planBronzeImage from "../assets/plan-bronze.webp";
import planSilverImage from "../assets/plan-silver.webp";
import planGoldImage from "../assets/plan-gold.webp";
import type { PublicPlan } from "../types";

const PLAN_IMAGES: Record<string, string> = { bronze: planBronzeImage, silver: planSilverImage, gold: planGoldImage };

export const MAX_EXTRA_OPERATORS = 500;
export { PLAN_IMAGES };

/** Standalone page kept for old links; the same flow is embedded in the account page. */
export default function Checkout() {
  const [params] = useSearchParams();
  return <CheckoutFlow initialPlan={params.get("plan")} />;
}

/** State and order submission shared by the checkout page and the checkout dialog. */
export function useCheckout(initialPlan: string | null) {
  const [plans, setPlans] = useState<PublicPlan[] | null>(null);
  const [taxPercent, setTaxPercent] = useState(0);
  const [extra, setExtra] = useState(0);
  const [form, setForm] = useState({ name: "", email: "", mobile: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [gateway, setGateway] = useState<GatewayCode | null>(null);
  const [anyMethod, setAnyMethod] = useState(true);
  // One order per distinct purchase: retrying after an error reuses it instead of piling up drafts.
  const orderKey = useRef<{ signature: string; key: string } | null>(null);
  const [picked, setPicked] = useState<string | null>(initialPlan);
  const sellable = (plans ?? []).filter((item) => item.sellable && !item.is_trial);
  // The requested plan when it can be bought, otherwise the first one on sale, so the page is never a dead end.
  const plan = sellable.find((item) => item.code === picked) ?? sellable[0] ?? null;

  useEffect(() => {
    request<PublicPlan[]>("/v1/plans")
      .then(setPlans)
      .catch((reason) => {
        setPlans([]);
        setError(billingErrorMessage(reason?.code, reason?.message, "دریافت اطلاعات پلن انجام نشد؛ صفحه را تازه کنید."));
      });
    request<{ tax_percent: number }>("/v1/billing/credit-settings")
      .then((settings) => setTaxPercent(settings.tax_percent))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    // Coming back from the bank with the back button restores this page with busy still set.
    const reset = (event: PageTransitionEvent) => event.persisted && setBusy(false);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  const lines = useMemo(() => {
    if (!plan) return { base: 0, extras: 0, net: 0, tax: 0, total: 0 };
    const base = plan.annual_price_toman ?? 0;
    const extras = (plan.extra_operator_annual_toman ?? 0) * extra;
    const net = base + extras;
    const tax = Math.floor((net * taxPercent + 50) / 100);
    return { base, extras, net, tax, total: net + tax };
  }, [plan, extra, taxPercent]);

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    if (!plan) return;
    if (!termsAccepted) {
      setError("برای ادامه، قوانین، حریم خصوصی و سیاست لغو را بپذیرید.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = {
        plan_code: plan.code,
        billing_period: "annual",
        extra_operators: plan.allows_extra_operators ? extra : 0,
        customer_name: form.name,
        customer_email: form.email,
        customer_mobile: form.mobile,
        invoice_profile: {},
        terms_accepted: termsAccepted,
      };
      const signature = JSON.stringify(body);
      if (orderKey.current?.signature !== signature) orderKey.current = { signature, key: crypto.randomUUID() };
      const order = await request<{ id: string }>("/v1/orders", {
        method: "POST",
        headers: { "Idempotency-Key": orderKey.current.key },
        body,
      });
      await startPayment(order.id, gateway);
    } catch (reason) {
      const apiError = reason instanceof ApiError ? reason : null;
      setError(billingErrorMessage(apiError?.code, apiError?.message, "ساخت سفارش انجام نشد."));
      setBusy(false);
    }
  }

  return {
    plans, sellable, plan, picked, setPicked, taxPercent, extra, setExtra, form, setForm, error, busy,
    termsAccepted, setTermsAccepted, gateway, setGateway, anyMethod, setAnyMethod, lines, submit,
  };
}

/** Plan choice, buyer details and payment on one screen. `embedded` drops the page heading. */
export function CheckoutFlow({ initialPlan, embedded = false }: { initialPlan: string | null; embedded?: boolean }) {
  const {
    plans, sellable, plan, setPicked, taxPercent, extra, setExtra, form, setForm, error, busy,
    termsAccepted, setTermsAccepted, gateway, setGateway, anyMethod, setAnyMethod, lines, submit,
  } = useCheckout(initialPlan);
  if (plans === null) return <div className="card">در حال دریافت اطلاعات پلن…</div>;
  if (!plan) {
    return (
      <div className="card">
        <p className="commerce-error">{error || "در حال حاضر هیچ پلنی برای خرید در دسترس نیست؛ با پشتیبانی تماس بگیرید."}</p>
        <Link className="btn-ghost" to="/account">بازگشت به حساب</Link>
      </div>
    );
  }
  return (
    <div className={`commerce-page${embedded ? " is-embedded" : ""}`}>
      <div className="commerce-heading">
        {embedded ? null : <h1>خرید اشتراک</h1>}
        <p>مبلغ نهایی در سرور محاسبه می‌شود.{taxPercent ? ` قیمت پلن بدون مالیات است و ${fmt.int(taxPercent)}٪ مالیات به مبلغ اضافه می‌شود.` : " قیمت نمایش‌داده‌شده شامل مالیات است."}</p>
      </div>
      {error ? <div className="commerce-error" role="alert">{error}</div> : null}
      <div className="plan-picker" role="radiogroup" aria-label="انتخاب پلن">
        {sellable.map((item) => (
          <button
            key={item.code}
            type="button"
            role="radio"
            aria-checked={item.code === plan.code}
            className={`plan-option${item.code === plan.code ? " is-selected" : ""}`}
            onClick={() => setPicked(item.code)}
          >
            {PLAN_IMAGES[item.code] ? <img src={PLAN_IMAGES[item.code]} alt="" className="plan-option__image" /> : null}
            <strong>{item.name}</strong>
            <span>{fmt.toman(item.annual_price_toman ?? 0)} / سال</span>
          </button>
        ))}
      </div>
      <div className="commerce-grid">
        <form className="card commerce-form" onSubmit={submit}>
          <p className="text-sm text-slate-500">دوره پرداخت اشتراک: سالانه</p>
          {plan.allows_extra_operators ? (
            <label>
              اپراتور اضافه
              <input
                type="number"
                min={0}
                max={MAX_EXTRA_OPERATORS}
                inputMode="numeric"
                value={extra}
                onChange={(event) => setExtra(Math.max(0, Math.min(MAX_EXTRA_OPERATORS, Number(fmt.latinDigits(event.target.value)) || 0)))}
              />
            </label>
          ) : null}
          <label>نام خریدار<input required autoComplete="name" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
          <label>ایمیل<input type="email" dir="ltr" required autoComplete="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
          <label>موبایل<input type="tel" dir="ltr" required autoComplete="tel" value={form.mobile} onChange={(event) => setForm({ ...form, mobile: fmt.latinDigits(event.target.value) })} /></label>
          <ToggleSwitch className="terms-check" checked={termsAccepted} onChange={setTermsAccepted} label="قوانین، حریم خصوصی و سیاست لغو را می‌پذیرم." />
          <p className="field-hint">
            متن کامل: <Link to="/terms" target="_blank">قوانین</Link>، <Link to="/privacy" target="_blank">حریم خصوصی</Link>، <Link to="/cancellation" target="_blank">سیاست لغو</Link>
          </p>
          <PaymentMethodPicker amountToman={lines.total} value={gateway} onChange={setGateway} onAvailability={setAnyMethod} />
          <button className="btn" disabled={busy || !anyMethod || !gateway}>{busy ? "در حال انتقال…" : "پرداخت امن"}</button>
        </form>
        <aside className="card order-summary">
          <h2>خلاصه سفارش</h2>
          <div><span>اشتراک سالانه</span><strong>{fmt.toman(lines.base)}</strong></div>
          {extra && plan.allows_extra_operators ? <div><span>{fmt.int(extra)} اپراتور اضافه</span><strong>{fmt.toman(lines.extras)}</strong></div> : null}
          {taxPercent ? <div><span>مالیات ({fmt.int(taxPercent)}٪)</span><strong>{fmt.toman(lines.tax)}</strong></div> : null}
          <hr />
          <div className="summary-total"><span>مبلغ نهایی</span><strong>{fmt.toman(lines.total)}</strong></div>
        </aside>
      </div>
    </div>
  );
}
