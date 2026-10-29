import { useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import type { Page, SubscriptionAdmin } from "../types";
import { FilterSelect, useFilterBar } from "@cbi/web-shared/components/FilterBar";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";

const COLUMNS: SkeletonColumn[] = [
  { label: "سازمان", width: "8rem" },
  { label: "پلن", width: "6rem" },
  { label: "وضعیت", width: "4rem" },
  { label: "دوره", width: "4rem" },
  { label: "ظرفیت", width: "2rem" },
  { label: "سررسید", width: "5rem" },
  { label: "عملیات", width: "11rem", height: "2.125rem" },
];

const STATUS_LABELS: Record<string, string> = { active: "فعال", trialing: "آزمایشی", pending_payment: "در انتظار پرداخت", expired: "منقضی", canceled: "لغوشده" };

export default function Subscriptions() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const subscriptions = useResource<Page<SubscriptionAdmin>>((signal) => {
    const params = new URLSearchParams({limit: String(limit), cursor: String(offset)});
    if (status) params.set("status", status);
    if (query.trim()) params.set("q", query.trim());
    return request<Page<SubscriptionAdmin>>(`/v1/admin/commerce/subscriptions?${params}`, { signal });
  }, [offset, query, status]);
  const page = subscriptions.data;

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
      subscriptions.reload();
    } catch (reasonValue) { setError((reasonValue as Error).message); }
  }

  const filterBar = useFilterBar({ hasActive: Boolean(query || status), onClear: () => { setQuery(""); setStatus(""); setOffset(0); }, fields: [ { id: "query", label: "جست‌وجوی سازمان یا پلن", active: Boolean(query), onRemove: () => { setQuery(""); setOffset(0); }, className: "sm:w-64", control: <input className="input" value={query} onChange={(event) => { setQuery(event.target.value); setOffset(0); }} /> }, { id: "status", label: "وضعیت", active: Boolean(status), onRemove: () => { setStatus(""); setOffset(0); }, control: <FilterSelect value={status} onChange={(value) => { setStatus(value); setOffset(0); }} options={Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label }))} /> }, ] });

  return <div className="space-y-4">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-2xl font-bold">مرکز اشتراک‌ها</h1><p className="mt-1 text-sm text-slate-500">وضعیت، سررسید، ظرفیت و عملیات کنترل‌شده اشتراک سازمان‌ها</p></div>{filterBar.toolbar}</div>
    <ErrorBox message={subscriptions.error ?? error}/>
    {filterBar.fields}
    <div className="card overflow-x-auto">{subscriptions.loading ? <SkeletonTable columns={COLUMNS} rows={page?.items.length ? Math.min(page.items.length, limit) : 8} /> : !page || page.items.length === 0 ? <Empty/> : <table className="table"><thead><tr><th>سازمان</th><th>پلن</th><th>وضعیت</th><th>دوره</th><th>ظرفیت</th><th>سررسید</th><th>عملیات</th></tr></thead><tbody>{page.items.map((item) => <tr key={item.id}><td><Link className="text-brand-600" to={`/tenants/${item.tenant_id}`}>{item.tenant_name}</Link></td><td>{item.plan_name} / {fmt.int(item.plan_version)}</td><td>{STATUS_LABELS[item.status] ?? item.status}{item.cancel_at_period_end ? <small className="block text-amber-600">لغو در پایان دوره</small> : null}</td><td>{item.billing_period === 'annual' ? 'سالانه' : item.billing_period === 'legacy_monthly' ? 'ماهانه (اشتراک قدیمی)' : item.billing_period === 'trial' ? 'آزمایشی' : item.billing_period}</td><td>{fmt.int(item.base_operators + item.extra_operators)}</td><td>{fmt.date(item.period_end)}</td><td><select className="input min-w-44 text-xs" defaultValue="" onChange={(event) => { const value=event.target.value; event.target.value=""; if(value) void action(item,value); }}><option value="">انتخاب عملیات</option><option value="cancel_at_period_end">لغو پایان دوره</option><option value="resume">ادامه اشتراک</option><option value="extend">تمدید دستی</option>{item.status === 'trialing' ? <option value="extend_trial">تمدید آزمایشی</option> : null}<option value="stop_now">توقف فوری</option></select></td></tr>)}</tbody></table>}</div>
    {page?<Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset}/>:null}
  </div>;
}
