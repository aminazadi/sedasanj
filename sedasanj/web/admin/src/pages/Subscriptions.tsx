import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Page, SubscriptionAdmin } from "../types";
import TableFilters from "@cbi/web-shared/components/TableFilters";

const STATUS_LABELS: Record<string, string> = { active: "فعال", trialing: "آزمایشی", pending_payment: "در انتظار پرداخت", expired: "منقضی", canceled: "لغوشده" };

export default function Subscriptions() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<SubscriptionAdmin> | null>(null);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({limit: String(limit), cursor: String(offset)});
      if (status) params.set("status", status);
      if (query.trim()) params.set("q", query.trim());
      setPage(await request<Page<SubscriptionAdmin>>(`/v1/admin/commerce/subscriptions?${params}`));
    } catch (reason) { setError((reason as Error).message); }
  }, [offset, query, status]);
  useEffect(() => { void load(); }, [load]);

  async function action(item: SubscriptionAdmin, type: string) {
    const reason = window.prompt("دلیل این عملیات را وارد کنید");
    if (!reason) return;
    let days: number | undefined;
    if (type === "extend" || type === "extend_trial") {
      const raw = window.prompt("تعداد روز را وارد کنید", "30");
      if (!raw) return;
      days = Number(fmt.latinDigits(raw));
    }
    if (type === "stop_now" && !window.confirm("اشتراک فوراً متوقف شود؟")) return;
    try {
      await request(`/v1/admin/commerce/subscriptions/${item.id}/actions`, {method: "POST", body: {action: type, reason, days}});
      await load();
    } catch (reasonValue) { setError((reasonValue as Error).message); }
  }

  return <div className="space-y-4">
    <div><h1 className="text-2xl font-bold">مرکز اشتراک‌ها</h1><p className="mt-1 text-sm text-slate-500">وضعیت، سررسید، ظرفیت و عملیات کنترل‌شده اشتراک سازمان‌ها</p></div>
    <ErrorBox message={error}/>
    <TableFilters><div className="flex flex-wrap gap-3"><input className="input max-w-sm" placeholder="جست‌وجوی سازمان یا پلن" value={query} onChange={(event) => {setQuery(event.target.value);setOffset(0);}}/><select className="input max-w-48" value={status} onChange={(event) => {setStatus(event.target.value);setOffset(0);}}><option value="">همه وضعیت‌ها</option>{Object.entries(STATUS_LABELS).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></div></TableFilters>
    <div className="card overflow-x-auto">{!page ? <Loading/> : page.items.length === 0 ? <Empty/> : <table className="table"><thead><tr><th>سازمان</th><th>پلن</th><th>وضعیت</th><th>دوره</th><th>ظرفیت</th><th>سررسید</th><th>عملیات</th></tr></thead><tbody>{page.items.map((item) => <tr key={item.id}><td><Link className="text-brand-600" to={`/tenants/${item.tenant_id}`}>{item.tenant_name}</Link></td><td>{item.plan_name} / {fmt.int(item.plan_version)}</td><td>{STATUS_LABELS[item.status] ?? item.status}{item.cancel_at_period_end ? <small className="block text-amber-600">لغو در پایان دوره</small> : null}</td><td>{item.billing_period === 'annual' ? 'سالانه' : item.billing_period === 'monthly' ? 'ماهانه' : item.billing_period}</td><td>{fmt.int(item.base_operators + item.extra_operators)}</td><td>{fmt.date(item.period_end)}</td><td><select className="input min-w-44 text-xs" defaultValue="" onChange={(event) => { const value=event.target.value; event.target.value=""; if(value) void action(item,value); }}><option value="">انتخاب عملیات</option><option value="cancel_at_period_end">لغو پایان دوره</option><option value="resume">ادامه اشتراک</option><option value="extend">تمدید دستی</option>{item.status === 'trialing' ? <option value="extend_trial">تمدید آزمایشی</option> : null}<option value="stop_now">توقف فوری</option></select></td></tr>)}</tbody></table>}</div>
    {page?<Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset}/>:null}
  </div>;
}
