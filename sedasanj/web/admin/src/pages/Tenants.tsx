import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Page, Tenant } from "../types";

const EMPTY_FORM = {
  name: "",
  price_per_minute_toman: 10000,
  admin_email: "",
  admin_password: "",
  audio_retention_days: 30,
  max_concurrent_jobs: 10,
  max_operators: 5,
  plan_code: "legacy_custom",
  billing_period: "legacy",
};

export default function Tenants() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Tenant> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [open, setOpen] = useState(false);
  const [planCodes, setPlanCodes] = useState<Array<{code:string;name:string}>>([]);

  async function reload() {
    try {
      setPage(await request<Page<Tenant>>(`/v1/admin/tenants?offset=${offset}&limit=${limit}`));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    void reload();
    request<Page<{code:string;name:string;status:string}>>("/v1/admin/commerce/plans?limit=200").then((page) => setPlanCodes(Array.from(new Map(page.items.filter((row) => row.status === "published").map((row) => [row.code, {code: row.code, name: row.name}])).values()))).catch(() => undefined);
  }, [offset]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await request<Tenant>("/v1/admin/tenants", { method: "POST", body: form });
      setForm(EMPTY_FORM);
      setOpen(false);
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!page) return <Loading />;
  const tenants = page.items;

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />
      <div className="flex justify-between">
        <h1 className="text-lg font-bold">مشتریان</h1>
        <button className="btn" onClick={() => setOpen(!open)}>
          {open ? "بستن" : "مشتری جدید"}
        </button>
      </div>

      {open ? (
        <form className="card grid gap-3 md:grid-cols-3" onSubmit={create}>
          <div>
            <label className="label">نام سازمان</label>
            <input
              className="input"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
          </div>
          <div><label className="label">پلن اولیه</label><select className="input" value={form.plan_code} onChange={(event) => setForm({...form, plan_code: event.target.value})}>{planCodes.map((plan) => <option key={plan.code} value={plan.code}>{plan.name}</option>)}</select></div>
          <div><label className="label">دوره اشتراک</label><select className="input" value={form.billing_period} onChange={(event) => setForm({...form, billing_period: event.target.value})}><option value="legacy">نامحدود سفارشی</option><option value="monthly">ماهانه</option><option value="annual">سالانه</option></select></div>
          <div>
            <label className="label">نرخ هر دقیقه (تومان)</label>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              value={fmt.digits(form.price_per_minute_toman)}
              onChange={(event) =>
                setForm({
                  ...form,
                  price_per_minute_toman: Number(fmt.latinDigits(event.target.value)),
                })
              }
              required
            />
          </div>
          <div>
            <label className="label">نگهداشت صوت (روز)</label>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              value={fmt.digits(form.audio_retention_days)}
              onChange={(event) =>
                setForm({
                  ...form,
                  audio_retention_days: Number(fmt.latinDigits(event.target.value)),
                })
              }
            />
          </div>
          <div>
            <label className="label">ایمیل مدیر سازمان</label>
            <input
              className="input"
              type="email"
              dir="ltr"
              value={form.admin_email}
              onChange={(event) => setForm({ ...form, admin_email: event.target.value })}
              required
            />
          </div>
          <div>
            <label className="label">گذرواژه مدیر</label>
            <input
              className="input"
              type="password"
              dir="ltr"
              minLength={8}
              value={form.admin_password}
              onChange={(event) => setForm({ ...form, admin_password: event.target.value })}
              required
            />
          </div>
          <div>
            <label className="label">حداکثر اپراتور</label>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              value={fmt.digits(form.max_operators)}
              onChange={(event) =>
                setForm({
                  ...form,
                  max_operators: Number(fmt.latinDigits(event.target.value)),
                })
              }
            />
          </div>
          <div className="flex items-end">
            <button className="btn w-full">ایجاد</button>
          </div>
        </form>
      ) : null}

      <div className="card">
        {tenants.length === 0 ? (
          <Empty />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>نام</th>
                <th>وضعیت</th>
                <th>نرخ دقیقه</th>
                <th>سهمیه ماهانه</th>
                <th>اپراتور</th>
                <th>نگهداشت</th>
                <th>ایجاد</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((tenant) => (
                <tr key={tenant.id}>
                  <td>
                    <Link className="text-brand-600" to={`/tenants/${tenant.id}`}>
                      {tenant.name}
                    </Link>
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        tenant.status === "active"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-rose-50 text-rose-700"
                      }`}
                    >
                      {tenant.status === "active" ? "فعال" : "معلق"}
                    </span>
                  </td>
                  <td>{fmt.toman(tenant.price_per_minute_toman)}</td>
                  <td>{tenant.monthly_minute_quota ? fmt.int(tenant.monthly_minute_quota) : "—"}</td>
                  <td>{fmt.int(tenant.max_operators)}</td>
                  <td>{fmt.int(tenant.audio_retention_days)} روز</td>
                  <td>{fmt.date(tenant.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} />
    </div>
  );
}
