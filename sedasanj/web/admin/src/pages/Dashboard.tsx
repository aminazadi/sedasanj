import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { ErrorBox, Loading, Stat } from "../components/Widgets";
import type { Kpis } from "../types";

const QUEUE_LABELS: Record<string, string> = {
  asr: "پیاده‌سازی صوت",
  llm: "تحلیل زبانی",
  notify: "اطلاع‌رسانی",
};

export default function Dashboard() {
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [commerce, setCommerce] = useState<{revenue_month_toman:number;pending_orders:number;payments_need_attention:number;subscriptions:Record<string,number>;renewals_due:number;refunds_total_toman:number;new_leads:number;open_installations:number;missing_subscriptions:number}|null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => Promise.all([
      request<Kpis>("/v1/admin/kpis"),
      request<{revenue_month_toman:number;pending_orders:number;payments_need_attention:number;subscriptions:Record<string,number>;renewals_due:number;refunds_total_toman:number;new_leads:number;open_installations:number;missing_subscriptions:number}>("/v1/admin/commerce/overview"),
    ]).then(([operational, financial]) => { setKpis(operational); setCommerce(financial); }).catch((err) => setError(err.message));
    void load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!kpis) return <Loading />;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-4">
        <Stat title="مشتریان فعال" value={fmt.int(kpis.tenants_active)} />
        <Stat title="تماس امروز" value={fmt.int(kpis.calls_today)} />
        <Stat
          title="خطای امروز"
          value={fmt.int(kpis.calls_failed_today)}
          tone={kpis.calls_failed_today > 0 ? "text-rose-600" : undefined}
        />
        <Stat title="دقایق امروز" value={fmt.int(kpis.minutes_today)} />
      </div>
      {commerce ? <><div className="grid gap-4 md:grid-cols-4"><Stat title="درآمد ماه" value={fmt.toman(commerce.revenue_month_toman)}/><Stat title="سفارش در انتظار" value={fmt.int(commerce.pending_orders)} tone={commerce.pending_orders ? "text-amber-600" : undefined}/><Stat title="پرداخت نیازمند بررسی" value={fmt.int(commerce.payments_need_attention)} tone={commerce.payments_need_attention ? "text-rose-600" : undefined}/><Stat title="تمدید هفت روز آینده" value={fmt.int(commerce.renewals_due)}/></div>{commerce.missing_subscriptions ? <Link className="block rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700" to="/subscriptions">{fmt.int(commerce.missing_subscriptions)} سازمان بدون اشتراک معتبر شناسایی شد.</Link> : null}</> : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card">
          <h2 className="mb-3 font-bold">عمق صف‌ها</h2>
          <table className="table">
            <thead>
              <tr>
                <th>صف</th>
                <th>تعداد در انتظار</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(kpis.queue_depth).map(([queue, depth]) => (
                <tr key={queue}>
                  <td>{QUEUE_LABELS[queue] ?? queue}</td>
                  <td>{fmt.int(depth)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h2 className="mb-3 font-bold">کارهای در انتظار تلاش مجدد</h2>
          <div className="text-3xl font-bold">{fmt.int(kpis.jobs_failed_retryable)}</div>
          <Link className="mt-3 inline-block text-sm text-brand-600" to="/jobs">
            مدیریت کارها
          </Link>
        </div>
      </div>
    </div>
  );
}
