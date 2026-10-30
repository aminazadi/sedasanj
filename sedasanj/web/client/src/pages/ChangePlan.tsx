import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import PaymentMethodPicker from "../components/PaymentMethodPicker";
import { billingErrorMessage } from "../lib/billingErrors.mjs";
import { startPayment, type GatewayCode } from "../lib/payment";
import type { PublicPlan, SubscriptionInfo } from "../types";

type ChangeResult =
  | { status: "payment_required"; change_id: string; order_id: string; amount_toman: number }
  | { status: "scheduled"; change_id: string; effective_at: string };

/** Switch an active subscription to another plan: upgrades are paid now, downgrades start at renewal. */
export default function ChangePlan() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [plans, setPlans] = useState<PublicPlan[]>([]);
  const [current, setCurrent] = useState<SubscriptionInfo | null>(null);
  const [extra, setExtra] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [order, setOrder] = useState<{ id: string; amount: number } | null>(null);
  const [gateway, setGateway] = useState<GatewayCode | null>(null);
  const [anyMethod, setAnyMethod] = useState(true);
  // One change per distinct choice: a retry after an error replays it instead of creating another.
  const changeKey = useRef<{ signature: string; key: string } | null>(null);
  const code = params.get("plan");

  useEffect(() => {
    Promise.all([request<PublicPlan[]>("/v1/plans"), request<SubscriptionInfo>("/v1/subscription")])
      .then(([planList, subscription]) => {
        setPlans(planList.filter((item) => item.sellable && !item.is_trial));
        setCurrent(subscription);
        setExtra(subscription.extra_operators);
      })
      .catch((reason) => setError(billingErrorMessage(reason?.code, reason?.message, "دریافت اطلاعات پلن‌ها انجام نشد.")));
  }, []);

  useEffect(() => {
    const reset = (event: PageTransitionEvent) => event.persisted && setBusy(false);
    window.addEventListener("pageshow", reset);
    return () => window.removeEventListener("pageshow", reset);
  }, []);

  const target = plans.find((item) => item.code === code) ?? null;
  const total = useMemo(
    () => (target ? (target.annual_price_toman ?? 0) + (target.extra_operator_annual_toman ?? 0) * extra : 0),
    [target, extra],
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!target) return;
    setBusy(true);
    setError("");
    try {
      const signature = `${target.code}:${target.allows_extra_operators ? extra : 0}`;
      if (changeKey.current?.signature !== signature) changeKey.current = { signature, key: crypto.randomUUID() };
      const result = await request<ChangeResult>("/v1/subscription/change", {
        method: "POST",
        headers: { "Idempotency-Key": changeKey.current.key },
        body: { plan_code: target.code, extra_operators: target.allows_extra_operators ? extra : 0 },
      });
      if (result.status === "scheduled") {
        navigate("/account", { replace: true });
        return;
      }
      setOrder({ id: result.order_id, amount: result.amount_toman });
      setBusy(false);
    } catch (reason) {
      const apiError = reason instanceof ApiError ? reason : null;
      setError(billingErrorMessage(apiError?.code, apiError?.message, "ثبت تغییر پلن انجام نشد."));
      setBusy(false);
    }
  }

  async function pay() {
    if (!order) return;
    setBusy(true);
    setError("");
    try {
      await startPayment(order.id, gateway);
    } catch (reason) {
      const apiError = reason instanceof ApiError ? reason : null;
      setError(billingErrorMessage(apiError?.code, apiError?.message, "انتقال به درگاه انجام نشد."));
      setBusy(false);
    }
  }

  if (!current && !error) return <div className="card">در حال دریافت اطلاعات اشتراک…</div>;
  return (
    <div className="commerce-page">
      <div className="commerce-heading">
        <h1>تغییر پلن</h1>
        <p>پلن فعلی: {current?.plan_name ?? "—"}. ارتقا همین حالا و به نسبت زمان باقی‌مانده پرداخت می‌شود؛ تنزل از پایان دوره فعلی اعمال می‌شود.</p>
      </div>
      {error ? <div className="commerce-error">{error}</div> : null}
      <div className="commerce-grid">
        <form className="card commerce-form" onSubmit={submit}>
          <div role="radiogroup" aria-label="پلن جدید" className="grid gap-2">
            {plans.map((item) => (
              <label key={item.code} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="plan"
                    checked={code === item.code}
                    disabled={item.code === current?.plan_code}
                    onChange={() => setParams({ plan: item.code }, { replace: true })}
                  />
                  {item.name}
                  {item.code === current?.plan_code ? " (پلن فعلی)" : ""}
                </span>
                <strong>{fmt.toman(item.annual_price_toman ?? 0)} / سال</strong>
              </label>
            ))}
          </div>
          {target?.allows_extra_operators ? (
            <label>
              اپراتور اضافه
              <input type="number" min={0} max={500} inputMode="numeric" value={extra} onChange={(event) => setExtra(Math.max(0, Math.min(500, Number(fmt.latinDigits(event.target.value)) || 0)))} />
            </label>
          ) : null}
          {order ? (
            <>
              <p className="text-sm">مبلغ قابل پرداخت برای ارتقا: <strong>{fmt.toman(order.amount)}</strong></p>
              <PaymentMethodPicker amountToman={order.amount} value={gateway} onChange={setGateway} onAvailability={setAnyMethod} />
              <button type="button" className="btn" disabled={busy || !anyMethod || !gateway} onClick={() => void pay()}>
                {busy ? "در حال انتقال…" : "پرداخت امن"}
              </button>
            </>
          ) : (
            <button className="btn" disabled={busy || !target}>{busy ? "در حال ثبت…" : "ادامه"}</button>
          )}
          <Link className="btn-ghost" to="/account">بازگشت به حساب</Link>
        </form>
        <aside className="card order-summary">
          <h2>خلاصه</h2>
          <div><span>قیمت سالانه پلن جدید</span><strong>{target ? fmt.toman(total) : "—"}</strong></div>
          <p className="field-hint">مبلغ دقیق ارتقا، شامل مالیات و تعدیل زمان باقی‌مانده، پس از ادامه در سرور محاسبه و نمایش داده می‌شود.</p>
        </aside>
      </div>
    </div>
  );
}
