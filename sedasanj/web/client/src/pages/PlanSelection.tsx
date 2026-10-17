import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { BrandLogo } from "../components/BrandLogo";
import type { PublicPlan } from "../types";
import planBronzeImage from "../assets/plan-bronze.png";
import planSilverImage from "../assets/plan-silver.png";
import planGoldImage from "../assets/plan-gold.png";

const planImages: Record<string, string> = {
  bronze: planBronzeImage,
  silver: planSilverImage,
  gold: planGoldImage,
};

export default function PlanSelection() {
  const [plans, setPlans] = useState<PublicPlan[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    request<PublicPlan[]>("/v1/plans")
      .then((items) => setPlans(items.filter((plan) => plan.code !== "demo")))
      .catch((reason) => setError(reason.message));
  }, []);

  return <main className="plan-selection-shell" dir="rtl"><div className="plan-selection-page">
    <div className="checkout-brand"><Link to="/" aria-label="صفحه اصلی"><BrandLogo animated className="block w-48 sm:w-56" title="صداسنج" /></Link></div>
    <section className="plan-selection-panel">
      <header className="plan-selection-heading"><span>ارتقای اشتراک</span><h1>پلن مناسب سازمان خود را انتخاب کنید</h1><p>تمام پلن‌ها سالانه هستند و ظرفیت هر پلن متناسب با اندازه تیم شما تنظیم شده است.</p></header>
      {error ? <div className="commerce-error">{error}</div> : null}
      {!error && !plans.length ? <p className="checkout-loading">در حال دریافت پلن‌ها…</p> : null}
      <div className="upgrade-plans">{plans.map((plan) => <article className={plan.code === "silver" ? "upgrade-plan is-featured" : "upgrade-plan"} key={plan.code}>
        <img src={planImages[plan.code] ?? planBronzeImage} alt={`تصویر پلن ${plan.name}`} />
        <h2>{plan.name}</h2>
        <div className="upgrade-plan-price"><strong>{plan.annual_price_toman == null ? "تماس بگیرید" : fmt.int(plan.annual_price_toman)}</strong>{plan.annual_price_toman != null ? <span>تومان / سال</span> : null}</div>
        <ul><li>{fmt.int(plan.base_operators)} کاربر اپراتور</li><li>{fmt.int(plan.intro_minutes)} دقیقه رایگان در ماه</li><li>{fmt.int(plan.assistant_monthly_messages)} پیام دستیار در ماه</li></ul>
        <Link className="btn" to={`/checkout?plan=${encodeURIComponent(plan.code)}`}>انتخاب پلن {plan.name}</Link>
      </article>)}</div>
      <p className="checkout-back"><Link to="/account">بازگشت به حساب</Link></p>
    </section>
  </div></main>;
}
