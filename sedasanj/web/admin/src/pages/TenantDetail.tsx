import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination, Stat } from "../components/Widgets";
import type { LedgerEntry, Page, TenantDetail, TenantUser } from "../types";

export default function TenantDetailPage() {
  const limit = 10;
  const [userOffset, setUserOffset] = useState(0);
  const [userPage, setUserPage] = useState<Page<TenantUser> | null>(null);
  const [ledgerOffset, setLedgerOffset] = useState(0);
  const [ledgerTotal, setLedgerTotal] = useState(0);
  const { tenantId } = useParams<{ tenantId: string }>();
  const [tenant, setTenant] = useState<TenantDetail | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [topup, setTopup] = useState({ minutes: 100, toman: "", note: "" });
  const [settingsDraft, setSettingsDraft] = useState({ max_concurrent_jobs: 0, audio_retention_days: 0 });
  const [commerce, setCommerce] = useState<{subscriptions:Array<Record<string,unknown>>;orders:Array<Record<string,unknown>>;credit_grants:Array<Record<string,unknown>>;reservations:Array<Record<string,unknown>>;assistant_messages_total:number;audit:Array<Record<string,unknown>>}|null>(null);

  async function reload() {
    try {
      const [detail, userData, entries, commerceData] = await Promise.all([
        request<TenantDetail>(`/v1/admin/tenants/${tenantId}`),
        request<Page<TenantUser>>(`/v1/admin/tenants/${tenantId}/users?limit=${limit}&offset=${userOffset}`),
        request<Page<LedgerEntry>>(`/v1/admin/tenants/${tenantId}/ledger?limit=${limit}&offset=${ledgerOffset}`),
        request<{subscriptions:Array<Record<string,unknown>>;orders:Array<Record<string,unknown>>;credit_grants:Array<Record<string,unknown>>;reservations:Array<Record<string,unknown>>;assistant_messages_total:number;audit:Array<Record<string,unknown>>}>(`/v1/admin/commerce/tenants/${tenantId}`),
      ]);
      setTenant(detail);
      setUserPage(userData);
      setLedger(entries.items);
      setLedgerTotal(entries.total);
      setCommerce(commerceData);
      setSettingsDraft({ max_concurrent_jobs: detail.max_concurrent_jobs, audio_retention_days: detail.audio_retention_days });
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    void reload();
  }, [ledgerOffset, tenantId, userOffset]);

  async function setStatus(action: "suspend" | "activate") {
    try {
      await request(`/v1/admin/tenants/${tenantId}/${action}`, { method: "POST" });
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function submitTopup(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await request(`/v1/admin/tenants/${tenantId}/topups`, {
        method: "POST",
        body: {
          minutes: topup.minutes,
          toman: topup.toman === "" ? null : Number(topup.toman),
          note: topup.note || null,
          idempotency_key: `admin-topup:${tenantId}:${Date.now()}`,
        },
      });
      setNotice("شارژ اعمال شد.");
      setTopup({ minutes: 100, toman: "", note: "" });
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function patchTenant(body: Record<string, unknown>) {
    try {
      await request(`/v1/admin/tenants/${tenantId}`, { method: "PATCH", body });
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!tenant) return <Loading />;

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />
      {notice ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
          {notice}
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold">{tenant.name}</h1>
        <div className="flex gap-2">
          {tenant.status === "active" ? (
            <button className="btn-ghost text-rose-700" onClick={() => void setStatus("suspend")}>
              تعلیق
            </button>
          ) : (
            <button className="btn-ghost" onClick={() => void setStatus("activate")}>
              فعال‌سازی
            </button>
          )}
          <Link className="btn-ghost" to="/tenants">
            بازگشت
          </Link>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Stat title="اعتبار" value={fmt.toman(tenant.balance_toman)} />
        <Stat title="اعتبار دقیقه" value={fmt.minutes(tenant.balance_seconds)} />
        <Stat title="کل تماس‌ها" value={fmt.int(tenant.calls_total)} />
        <Stat title="دقیقه رایگان ماهانه" value={fmt.int(tenant.plan_monthly_minutes ?? 0)} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <form className="card grid gap-3" onSubmit={submitTopup}>
          <h2 className="font-bold">شارژ دستی</h2>
          <div>
            <label className="label">دقیقه</label>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              value={fmt.digits(topup.minutes)}
              onChange={(event) =>
                setTopup({ ...topup, minutes: Number(fmt.latinDigits(event.target.value)) })
              }
              required
            />
          </div>
          <div>
            <label className="label">مبلغ تومان (اختیاری)</label>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              value={fmt.digits(topup.toman)}
              onChange={(event) =>
                setTopup({ ...topup, toman: fmt.latinDigits(event.target.value) })
              }
            />
          </div>
          <div>
            <label className="label">توضیح</label>
            <input
              className="input"
              value={topup.note}
              onChange={(event) => setTopup({ ...topup, note: event.target.value })}
            />
          </div>
          <button className="btn">اعمال شارژ</button>
        </form>

        <div className="card space-y-3">
          <h2 className="font-bold">تنظیمات سازمان</h2>
          <div>
            <label className="label">حداکثر کار همزمان</label>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              value={fmt.digits(settingsDraft.max_concurrent_jobs)}
              onChange={(event) => setSettingsDraft({...settingsDraft, max_concurrent_jobs: Number(fmt.latinDigits(event.target.value))})}
            />
          </div>
          <div>
            <label className="label">نگهداشت صوت (روز)</label>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              value={fmt.digits(settingsDraft.audio_retention_days)}
              onChange={(event) => setSettingsDraft({...settingsDraft, audio_retention_days: Number(fmt.latinDigits(event.target.value))})}
            />
          </div>
          <button className="btn" type="button" onClick={() => void patchTenant({max_concurrent_jobs: settingsDraft.max_concurrent_jobs, audio_retention_days: settingsDraft.audio_retention_days})}>ذخیره تنظیمات</button>
        </div>
      </div>

      <div className="card">
        <h2 className="mb-2 font-bold">کاربران</h2>
        {!userPage || userPage.items.length === 0 ? (
          <Empty />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ایمیل</th>
                <th>نقش</th>
                <th>موبایل</th>
                <th>داخلی</th>
                <th>ایجاد</th>
              </tr>
            </thead>
            <tbody>
              {userPage.items.map((user) => (
                <tr key={user.id}>
                  <td dir="ltr">{user.email}</td>
                  <td>
                    {user.role === "org_admin"
                      ? "مدیر سازمان"
                      : user.role === "operator"
                        ? "اپراتور"
                        : user.role === "viewer"
                          ? "بیننده"
                          : user.role}
                  </td>
                  <td dir="ltr">{user.mobile_number ? fmt.digits(user.mobile_number) : "—"}</td>
                  <td dir="ltr">{user.extension ? fmt.digits(user.extension) : "—"}</td>
                  <td>{fmt.date(user.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {userPage ? <Pagination offset={userOffset} limit={limit} total={userPage.total} onChange={setUserOffset} /> : null}
        <p className="mt-3 text-xs text-slate-400">
          اپراتور {fmt.int(tenant.users.filter((user) => user.role === "operator").length)} از{" "}
          {fmt.int(tenant.max_operators)} مجاز
        </p>
      </div>
      {commerce ? <div className="grid gap-4 md:grid-cols-2">
        <section className="card md:col-span-2 overflow-x-auto"><h2 className="mb-3 font-bold">اشتراک و مصرف</h2><p className="mb-2 text-sm">پیام‌های موفق دستیار: {fmt.int(commerce.assistant_messages_total)}</p>
          {commerce.subscriptions.length === 0 ? <Empty /> : <table className="table"><thead><tr><th>وضعیت</th><th>دوره</th><th>شروع</th><th>پایان</th><th>ظرفیت</th><th>نرخ دقیقه</th><th>پیام دستیار</th></tr></thead><tbody>{commerce.subscriptions.map((row) => <tr key={String(row.id)}><td>{String(row.status)}{row.cancel_at_period_end ? <small className="block text-amber-600">لغو در پایان دوره</small> : null}</td><td>{String(row.billing_period)}</td><td>{fmt.date(String(row.period_start))}</td><td>{fmt.date(String(row.period_end))}</td><td>{fmt.int(Number(row.base_operators) + Number(row.extra_operators))}</td><td>{fmt.toman(Number(row.price_per_minute_toman))}</td><td>{fmt.int(Number(row.assistant_monthly_messages))}</td></tr>)}</tbody></table>}
        </section>
        <section className="card overflow-x-auto"><h2 className="mb-3 font-bold">اعتبارها</h2>
          {commerce.credit_grants.length === 0 ? <Empty /> : <table className="table"><thead><tr><th>منبع</th><th>کل</th><th>باقی‌مانده</th><th>انقضا</th></tr></thead><tbody>{commerce.credit_grants.map((row) => <tr key={String(row.id)}><td>{String(row.source)}</td><td>{fmt.minutes(Number(row.total_seconds))}</td><td>{fmt.minutes(Number(row.remaining_seconds))}</td><td>{row.expires_at ? fmt.date(String(row.expires_at)) : "—"}</td></tr>)}</tbody></table>}
        </section>
        <section className="card overflow-x-auto"><h2 className="mb-3 font-bold">رزروهای باز</h2>
          {commerce.reservations.length === 0 ? <Empty /> : <table className="table"><thead><tr><th>وضعیت</th><th>مدت</th><th>زمان</th></tr></thead><tbody>{commerce.reservations.map((row) => <tr key={String(row.id)}><td>{String(row.status)}</td><td>{fmt.minutes(Number(row.seconds))}</td><td>{fmt.dateTime(String(row.created_at))}</td></tr>)}</tbody></table>}
        </section>
        <section className="card md:col-span-2 overflow-x-auto"><h2 className="mb-3 font-bold">سفارش‌های سازمان</h2>
          {commerce.orders.length === 0 ? <Empty /> : <table className="table"><thead><tr><th>شماره</th><th>نوع</th><th>وضعیت</th><th>مبلغ</th><th>ایجاد</th><th>پرداخت</th></tr></thead><tbody>{commerce.orders.map((row) => <tr key={String(row.id)}><td dir="ltr">{String(row.number)}</td><td>{String(row.kind)}</td><td>{String(row.status)}</td><td>{fmt.toman(Number(row.amount_toman))}</td><td>{fmt.dateTime(String(row.created_at))}</td><td>{row.paid_at ? fmt.dateTime(String(row.paid_at)) : "—"}</td></tr>)}</tbody></table>}
        </section>
      </div> : null}

      <div className="card">
        <h2 className="mb-2 font-bold">تراکنش‌های اعتبار</h2>
        {ledger.length === 0 ? (
          <Empty />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>زمان</th>
                <th>نوع</th>
                <th>ثانیه</th>
                <th>تومان</th>
              </tr>
            </thead>
            <tbody>
              {ledger.map((entry) => (
                <tr key={entry.id}>
                  <td>{fmt.dateTime(entry.created_at)}</td>
                  <td>{entry.kind}</td>
                  <td dir="ltr">{fmt.int(entry.seconds_delta)}</td>
                  <td dir="ltr">{fmt.int(entry.toman_delta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <Pagination offset={ledgerOffset} limit={limit} total={ledgerTotal} onChange={setLedgerOffset} />
      </div>
    </div>
  );
}
