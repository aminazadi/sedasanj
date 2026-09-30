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
  const [settingsDraft, setSettingsDraft] = useState({ monthly_minute_quota: 0, max_concurrent_jobs: 0, audio_retention_days: 0 });
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
      setSettingsDraft({ monthly_minute_quota: detail.monthly_minute_quota ?? 0, max_concurrent_jobs: detail.max_concurrent_jobs, audio_retention_days: detail.audio_retention_days });
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
        <Stat title="نرخ دقیقه" value={fmt.toman(tenant.price_per_minute_toman)} />
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
            <label className="label">سهمیه ماهانه (دقیقه)</label>
            <input
              className="input"
              type="text"
              inputMode="numeric"
              value={fmt.digits(settingsDraft.monthly_minute_quota)}
              onChange={(event) => setSettingsDraft({...settingsDraft, monthly_minute_quota: Number(fmt.latinDigits(event.target.value))})}
            />
          </div>
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
          <p className="text-xs text-slate-400">ظرفیت اپراتور و نرخ مصرف از اشتراک فعال خوانده می‌شود.</p>
          <button className="btn" type="button" onClick={() => void patchTenant({monthly_minute_quota: settingsDraft.monthly_minute_quota || null, max_concurrent_jobs: settingsDraft.max_concurrent_jobs, audio_retention_days: settingsDraft.audio_retention_days})}>ذخیره تنظیمات</button>
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
      {commerce ? <div className="grid gap-4 md:grid-cols-2"><section className="card"><h2 className="mb-3 font-bold">اشتراک و مصرف</h2><p className="text-sm">پیام‌های موفق دستیار: {fmt.int(commerce.assistant_messages_total)}</p><pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap text-xs" dir="ltr">{JSON.stringify(commerce.subscriptions, null, 2)}</pre></section><section className="card"><h2 className="mb-3 font-bold">اعتبارها و رزروها</h2><pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs" dir="ltr">{JSON.stringify({grants: commerce.credit_grants, reservations: commerce.reservations}, null, 2)}</pre></section><section className="card md:col-span-2"><h2 className="mb-3 font-bold">سفارش‌های سازمان</h2><pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs" dir="ltr">{JSON.stringify(commerce.orders, null, 2)}</pre></section></div> : null}

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
