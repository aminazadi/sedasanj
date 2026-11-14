import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { billingErrorMessage } from "../lib/billingErrors.mjs";
import type { PublicPlan } from "../types";

/** Plan chooser for signed-in organizations (trial, expired or canceled) that need a paid plan. */
export default function ChoosePlan() {
  const [plans, setPlans] = useState<PublicPlan[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    request<PublicPlan[]>("/v1/plans")
      .then((list) => setPlans(list.filter((plan) => plan.sellable && !plan.is_trial)))
      .catch((reason) => {
        setPlans([]);
        setError(billingErrorMessage(reason?.code, reason?.message, "دریافت پلن‌ها انجام نشد؛ صفحه را تازه کنید."));
      });
  }, []);

  if (plans === null) return <div className="card">در حال دریافت پلن‌ها…</div>;
  return (
    <div className="commerce-page">
      <div className="commerce-heading">
        <h1>انتخاب پلن</h1>
        <p>پلن مناسب را انتخاب کنید؛ مبلغ نهایی (با مالیات) در مرحله بعد نمایش داده می‌شود.</p>
      </div>
      {error ? <div className="commerce-error">{error}</div> : null}
      <div className="grid gap-4 md:grid-cols-3">
        {plans.map((plan) => (
          <div key={plan.code} className="card space-y-2">
            <h2 className="font-bold">{plan.name}</h2>
            <p>{fmt.toman(plan.annual_price_toman ?? 0)} / سال</p>
            <Link className="btn" to={`/checkout?plan=${encodeURIComponent(plan.code)}`}>خرید</Link>
          </div>
        ))}
      </div>
      <Link className="btn-ghost" to="/account">بازگشت به حساب</Link>
    </div>
  );
}
