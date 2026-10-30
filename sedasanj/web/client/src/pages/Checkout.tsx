import { useEffect, useMemo, useRef, useState } from "react";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import PaymentMethodPicker from "../components/PaymentMethodPicker";
import { billingErrorMessage } from "../lib/billingErrors.mjs";
import { startPayment, type GatewayCode } from "../lib/payment";
import type { PublicPlan } from "../types";

const MAX_EXTRA_OPERATORS = 500;

export default function Checkout() {
  const [params] = useSearchParams();
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
  const code = params.get("plan");
  const plan = plans?.find((item) => item.code === code && item.sellable && !item.is_trial) ?? null;

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

  if (plans === null) return <div className="card">در حال دریافت اطلاعات پلن…</div>;
  if (!plan) {
    return (
      <div className="card">
        <p className="commerce-error">{error || "پلن انتخاب‌شده پیدا نشد یا برای خرید در دسترس نیست."}</p>
        <Link className="btn" to="/#pricing">انتخاب پلن</Link>
      </div>
    );
  }
  return (
    <div className="commerce-page">
      <div className="commerce-heading">
        <h1>خرید اشتراک پلن {plan.name}</h1>
        <p>مبلغ نهایی در سرور محاسبه می‌شود.{taxPercent ? ` قیمت پلن بدون مالیات است و ${fmt.int(taxPercent)}٪ مالیات به مبلغ اضافه می‌شود.` : " قیمت نمایش‌داده‌شده شامل مالیات است."}</p>
      </div>
      {error ? <div className="commerce-error" role="alert">{error}</div> : null}
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
