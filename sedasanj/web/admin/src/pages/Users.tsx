import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, fmt, request, tokens } from "../api";
import { useReasonDialog } from "../components/ReasonDialog";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import { useTablePageSize } from "../lib/useTablePagination";
import { toOffset, useUrlParams } from "../lib/useUrlParams";
import type { Page, UserAdmin } from "../types";
import { FilterSelect, useFilterBar } from "@cbi/web-shared/components/FilterBar";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";

const COLUMNS: SkeletonColumn[] = [
  { label: "نام", width: "7rem" },
  { label: "موبایل", width: "6rem" },
  { label: "محصول", kind: "badge" },
  { label: "کانال", width: "4rem" },
  { label: "پلن", width: "5rem" },
  { label: "اشتراک", width: "4rem" },
  { label: "عضویت", width: "5rem" },
];

const PRODUCTS: Record<string, string> = { jalase_negar: "جلسه‌نگار", sedasanj: "صداسنج" };
const CHANNELS: Record<string, string> = { jalase_app: "اپ جلسه‌نگار", web: "وب", admin: "ادمین", quick_demo: "دموی سریع" };
const STATUSES: Record<string, string> = { active: "فعال", trialing: "آزمایشی", pending_payment: "در انتظار پرداخت", expired: "منقضی", canceled: "لغوشده" };
const ACTIONS: Record<string, string> = { suspend: "تعلیق حساب", unsuspend: "فعال‌سازی حساب", grant_credit: "اعطای اعتبار (دقیقه)", sms: "پیامک گروهی" };

type BulkAction = "suspend" | "unsuspend" | "grant_credit" | "sms";

export default function Users() {
  const [limit] = useTablePageSize();
  const [filters, setFilters] = useUrlParams({ offset: "0", q: "", product: "", channel: "", plan: "", status: "", linked: "" });
  const offset = toOffset(filters.offset);
  const setOffset = (value: number) => setFilters({ offset: String(value) });
  const patch = (value: Partial<typeof filters>) => setFilters({ ...value, offset: "0" });
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [action, setAction] = useState<BulkAction>("grant_credit");
  const [minutes, setMinutes] = useState("30");
  const [message, setMessage] = useState("");
  const [ask, dialog] = useReasonDialog();

  const query = () => {
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    if (filters.product) params.set("product", filters.product);
    if (filters.channel) params.set("signup_channel", filters.channel);
    if (filters.plan) params.set("plan_code", filters.plan);
    if (filters.status) params.set("subscription_status", filters.status);
    if (filters.linked) params.set("linked", filters.linked);
    return params;
  };
  const users = useResource<Page<UserAdmin>>((signal) => {
    const params = query();
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    return request<Page<UserAdmin>>(`/v1/admin/users?${params}`, { signal });
  }, [offset, limit, filters.q, filters.product, filters.channel, filters.plan, filters.status, filters.linked]);
  const page = users.data;
  const hasFilter = Boolean(filters.q || filters.product || filters.channel || filters.plan || filters.status || filters.linked);

  const filterBar = useFilterBar({
    hasActive: hasFilter,
    onClear: () => setFilters({ q: "", product: "", channel: "", plan: "", status: "", linked: "", offset: "0" }),
    fields: [
      { id: "q", label: "جست‌وجوی نام، موبایل یا ایمیل", active: Boolean(filters.q), onRemove: () => patch({ q: "" }), className: "sm:w-64", control: <input className="input" value={filters.q} onChange={(event) => patch({ q: event.target.value })} /> },
      { id: "product", label: "محصول", active: Boolean(filters.product), onRemove: () => patch({ product: "" }), control: <FilterSelect value={filters.product} onChange={(value) => patch({ product: value })} options={Object.entries(PRODUCTS).map(([value, label]) => ({ value, label }))} /> },
      { id: "channel", label: "کانال ثبت‌نام", active: Boolean(filters.channel), onRemove: () => patch({ channel: "" }), control: <FilterSelect value={filters.channel} onChange={(value) => patch({ channel: value })} options={Object.entries(CHANNELS).map(([value, label]) => ({ value, label }))} /> },
      { id: "plan", label: "کد پلن", active: Boolean(filters.plan), onRemove: () => patch({ plan: "" }), className: "sm:w-40", control: <input className="input" dir="ltr" value={filters.plan} onChange={(event) => patch({ plan: event.target.value.trim() })} /> },
      { id: "status", label: "وضعیت اشتراک", active: Boolean(filters.status), onRemove: () => patch({ status: "" }), control: <FilterSelect value={filters.status} onChange={(value) => patch({ status: value })} options={Object.entries(STATUSES).map(([value, label]) => ({ value, label }))} /> },
      { id: "linked", label: "اتصال به سازمان", active: Boolean(filters.linked), onRemove: () => patch({ linked: "" }), control: <FilterSelect value={filters.linked} onChange={(value) => patch({ linked: value })} options={[{ value: "true", label: "متصل به سازمان" }, { value: "false", label: "بدون اتصال" }]} /> },
    ],
  });

  async function exportFile(format: "csv" | "xlsx") {
    setError(null);
    try {
      const response = await fetch(`/v1/admin/users/export?${new URLSearchParams([...query(), ["format", format]])}`, {
        headers: { Authorization: `Bearer ${tokens.access() ?? ""}` },
      });
      if (!response.ok) throw new ApiError(response.status, "export", "خروجی ساخته نشد؛ فیلتر را محدودتر کنید و دوباره تلاش کنید.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `users.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function bulkBody(dryRun: boolean, note = "") {
    const filtersBody: Record<string, string> = {};
    if (filters.q) filtersBody.q = filters.q;
    if (filters.channel) filtersBody.signup_channel = filters.channel;
    if (filters.plan) filtersBody.plan_code = filters.plan;
    if (filters.status) filtersBody.subscription_status = filters.status;
    if (filters.linked) filtersBody.linked = filters.linked;
    return {
      action,
      filters: filtersBody,
      dry_run: dryRun,
      note,
      ...(action === "grant_credit" ? { minutes: Number(fmt.latinDigits(minutes)) } : {}),
      ...(action === "sms" ? { message } : {}),
    };
  }

  async function runBulk() {
    setError(null);
    setNotice(null);
    try {
      const preview = await request<{ count: number }>("/v1/admin/users/bulk", { method: "POST", body: bulkBody(true) });
      if (preview.count === 0) {
        setNotice("هیچ کاربر جلسه‌نگاری با این فیلترها پیدا نشد.");
        return;
      }
      const result = await ask(`«${ACTIONS[action]}» روی ${fmt.int(preview.count)} کاربر جلسه‌نگار اجرا می‌شود. دلیل را بنویسید.`, { confirmLabel: "اجرا", destructive: action === "suspend" });
      if (!result) return;
      const done = await request<{ count: number; done: number }>("/v1/admin/users/bulk", { method: "POST", body: bulkBody(false, result.reason) });
      setNotice(`${fmt.int(done.done)} از ${fmt.int(done.count)} کاربر انجام شد.`);
      await users.reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      {dialog}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">کاربران</h1>
          <p className="mt-1 text-sm text-slate-500">همهٔ کاربران صداسنج و جلسه‌نگار، با فیلتر، خروجی و عملیات گروهی</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn-ghost text-sm" onClick={() => void exportFile("xlsx")}>خروجی Excel</button>
          <button className="btn-ghost text-sm" onClick={() => void exportFile("csv")}>خروجی CSV</button>
          {filterBar.toolbar}
        </div>
      </div>
      <ErrorBox message={users.error ?? error} />
      {notice ? <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</p> : null}
      {filterBar.fields}

      {filters.product === "jalase_negar" ? (
        <div className="card flex flex-wrap items-end gap-3">
          <div>
            <label className="label">عملیات گروهی روی نتیجهٔ فیلتر (حداکثر ۵۰۰ کاربر)</label>
            <select className="input" value={action} onChange={(event) => setAction(event.target.value as BulkAction)}>
              {Object.entries(ACTIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </div>
          {action === "grant_credit" ? (
            <div><label className="label">دقیقه</label><input className="input w-28" inputMode="numeric" dir="ltr" value={minutes} onChange={(event) => setMinutes(event.target.value)} /></div>
          ) : null}
          {action === "sms" ? (
            <div className="grow"><label className="label">متن پیام (حداکثر ۳۰۰ نویسه)</label><input className="input" maxLength={300} value={message} onChange={(event) => setMessage(event.target.value)} /></div>
          ) : null}
          <button className="btn" onClick={() => void runBulk()}>پیش‌نمایش و اجرا</button>
        </div>
      ) : (
        <p className="text-xs text-slate-500">برای عملیات گروهی، فیلتر محصول را روی «جلسه‌نگار» بگذارید.</p>
      )}

      <div className="card overflow-x-auto">
        {users.loading ? (
          <SkeletonTable columns={COLUMNS} rows={page?.items.length ? Math.min(page.items.length, limit) : 8} />
        ) : !page || page.items.length === 0 ? (
          <Empty />
        ) : (
          <table className="table">
            <thead><tr><th>نام</th><th>موبایل</th><th>محصول</th><th>کانال</th><th>پلن</th><th>اشتراک</th><th>وضعیت حساب</th><th>عضویت</th></tr></thead>
            <tbody>
              {page.items.map((item) => (
                <tr key={item.id}>
                  <td><Link className="text-brand-600" to={`/tenants/${item.tenant_id}`}>{item.name || item.tenant_name}</Link></td>
                  <td dir="ltr">{item.mobile ?? "—"}</td>
                  <td><span className={`badge ${item.product === "jalase_negar" ? "bg-sky-100 text-sky-800" : "bg-slate-100 text-slate-700"}`}>{PRODUCTS[item.product] ?? item.product}</span></td>
                  <td>{item.signup_channel ? CHANNELS[item.signup_channel] ?? item.signup_channel : "—"}</td>
                  <td>{item.plan_name ?? "—"}</td>
                  <td>{item.subscription_status ? STATUSES[item.subscription_status] ?? item.subscription_status : "—"}</td>
                  <td>{item.tenant_status === "active" ? "فعال" : item.tenant_status === "suspended" ? "معلق" : item.tenant_status}</td>
                  <td>{fmt.date(item.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
    </div>
  );
}
