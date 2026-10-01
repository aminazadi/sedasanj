import TwoFactorSettings from "../components/TwoFactorSettings";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { ROLE_LABELS, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import ApiKeyManager from "../components/ApiKeyManager";
import type {
  AccountInfo,
  ApiKey,
  Balance,
  LedgerEntry,
  Package,
  Page,
  User,
  Webhook,
  WebhookCreated,
} from "../types";

const EVENTS = ["call.complete", "call.failed", "balance.low", "sales.insight"];
const EVENT_LABELS: Record<string, string> = {
  "call.complete": "تماس تکمیل‌شده",
  "call.failed": "تماس ناموفق",
  "balance.low": "اعتبار رو به پایان",
  "sales.insight": "بینش فروش",
};

const LEDGER_LABELS: Record<string, string> = {
  reservation: "رزرو",
  settlement: "تسویه",
  release: "آزادسازی",
  topup: "شارژ",
  adjustment: "اصلاح",
  subscription_credit: "هدیه اشتراک",
  credit_purchase: "خرید اعتبار",
  expiration: "انقضای اعتبار",
  refund: "بازپرداخت",
};

const EMPTY_USER = {
  email: "",
  password: "",
  role: "operator",
  mobile_number: "",
  extension: "",
};

export default function Account() {
  const limit = 10;
  const { session } = useAuth();
  const isAdmin = session?.role === "org_admin";

  const [balance, setBalance] = useState<Balance | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [packages, setPackages] = useState<Package[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [maxOperators, setMaxOperators] = useState<number | null>(null);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [hookSecret, setHookSecret] = useState<string | null>(null);
  const [subscription, setSubscription] = useState<{ status: string; max_operators: number; assistant_monthly_messages: number; period_end: string | null } | null>(null);
  const [orders, setOrders] = useState<Array<{ id: string; number: string; kind: string; status: string; amount_toman: number; created_at: string }>>([]);
  const [ledgerOffset, setLedgerOffset] = useState(0);
  const [ledgerTotal, setLedgerTotal] = useState(0);
  const [orderOffset, setOrderOffset] = useState(0);
  const [orderTotal, setOrderTotal] = useState(0);
  const [userOffset, setUserOffset] = useState(0);
  const [userTotal, setUserTotal] = useState(0);
  const [keyOffset, setKeyOffset] = useState(0);
  const [keyTotal, setKeyTotal] = useState(0);
  const [hookOffset, setHookOffset] = useState(0);
  const [hookTotal, setHookTotal] = useState(0);

  const [userForm, setUserForm] = useState(EMPTY_USER);
  const [hookForm, setHookForm] = useState({ url: "", events: ["call.complete"] as string[] });

  async function reload() {
    try {
      const [balanceData, ledgerData, packagesData] = await Promise.all([
        request<Balance>("/v1/billing/balance"),
        request<Page<LedgerEntry>>(`/v1/billing/ledger?limit=${limit}&offset=${ledgerOffset}`),
        request<Package[]>("/v1/billing/packages"),
      ]);
      setBalance(balanceData);
      setLedger(ledgerData.items);
      setLedgerTotal(ledgerData.total);
      setPackages(packagesData);
      if (isAdmin) {
        const [keysData, hooksData, usersData, account, subscriptionData, orderData] = await Promise.all([
          request<Page<ApiKey>>(`/v1/auth/api-keys?limit=${limit}&offset=${keyOffset}`),
          request<Page<Webhook>>(`/v1/webhooks?limit=${limit}&offset=${hookOffset}`),
          request<Page<User>>(`/v1/auth/users?limit=${limit}&offset=${userOffset}`),
          request<AccountInfo>("/v1/account"),
          request<{ status: string; max_operators: number; assistant_monthly_messages: number; period_end: string | null }>("/v1/subscription"),
          request<Page<{ id: string; number: string; kind: string; status: string; amount_toman: number; created_at: string }>>(`/v1/orders?limit=${limit}&offset=${orderOffset}`),
        ]);
        setKeys(keysData.items);
        setKeyTotal(keysData.total);
        setHooks(hooksData.items);
        setHookTotal(hooksData.total);
        setUsers(usersData.items);
        setUserTotal(usersData.total);
        setMaxOperators(account.tenant.max_operators);
        setSubscription(subscriptionData);
        setOrders(orderData.items);
        setOrderTotal(orderData.total);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    void reload();
  }, [hookOffset, isAdmin, keyOffset, ledgerOffset, orderOffset, userOffset]);

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    try {
      await request<User>("/v1/auth/users", {
        method: "POST",
        body: {
          ...userForm,
          mobile_number: userForm.mobile_number || null,
          extension: userForm.extension || null,
        },
      });
      setUserForm(EMPTY_USER);
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function createHook(event: React.FormEvent) {
    event.preventDefault();
    try {
      const created = await request<WebhookCreated>("/v1/webhooks", {
        method: "POST",
        body: { url: hookForm.url, events: hookForm.events },
      });
      setHookSecret(created.secret);
      setHookForm({ url: "", events: ["call.complete"] });
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function exportUrl(format: string) {
    return `/v1/account/export?format=${format}`;
  }

  async function download(format: string) {
    const response = await fetch(exportUrl(format), {
      headers: { Authorization: `Bearer ${localStorage.getItem("cbi.access") ?? ""}` },
    });
    if (!response.ok) {
      setError("خروجی گرفتن ناموفق بود");
      return;
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `cbi-export.${format}`;
    link.click();
  }

  async function buyCredit(packageId: string) {
    try {
      const order = await request<{ id: string }>("/v1/billing/credit-orders", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: { package_id: packageId },
      });
      const payment = await request<{ redirect_url: string }>(`/v1/orders/${order.id}/pay`, { method: "POST" });
      window.location.assign(payment.redirect_url);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  if (!balance) return <Loading />;

  return (
    <div className="space-y-4">
      {isAdmin && <TwoFactorSettings />}
      <ErrorBox message={error} />

      <div className="grid gap-4 md:grid-cols-3">
        <div className="card">
          <h2 className="mb-2 font-bold">اعتبار</h2>
          <div className="text-2xl font-bold">{fmt.toman(balance.toman)}</div>
          <div className="text-sm text-slate-500">{fmt.int(balance.minutes)} دقیقه باقی‌مانده</div>
          <div className="mt-2 grid gap-1 text-xs text-slate-500">
            <span>هدیه زمان‌دار: {fmt.minutes(balance.expiring_seconds)}</span>
            <span>اعتبار دائمی: {fmt.minutes(balance.purchased_seconds)}</span>
          </div>
          <div className="mt-2 text-xs text-slate-400">
            نرخ: {fmt.toman(balance.price_per_minute_toman)} بر دقیقه
          </div>
        </div>
        <div className="card md:col-span-2">
          <h2 className="mb-2 font-bold">بسته‌ها</h2>
          {packages.length === 0 ? (
            <Empty />
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>نام</th>
                  <th>دقیقه</th>
                  <th>قیمت</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {packages.map((pkg) => (
                  <tr key={pkg.id}>
                    <td>{pkg.name}</td>
                    <td>{fmt.int(pkg.minutes)}</td>
                    <td>{fmt.toman(pkg.price_toman)}</td>
                    <td><button className="btn-ghost text-xs" onClick={() => void buyCredit(pkg.id)}>خرید</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {isAdmin && subscription ? (
        <div className="card">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="font-bold">اشتراک سازمان</h2><p className="mt-1 text-sm text-slate-500">وضعیت: {subscription.status} · ظرفیت {fmt.int(subscription.max_operators)} اپراتور · {fmt.int(subscription.assistant_monthly_messages)} پیام دستیار در ماه</p>{subscription.period_end ? <p className="mt-1 text-xs text-slate-400">سررسید: {fmt.date(subscription.period_end)}</p> : null}</div>
            <a className="btn" href="/#pricing">تغییر پلن</a>
          </div>
        </div>
      ) : null}

      {isAdmin && orders.length ? (
        <div className="card"><h2 className="mb-2 font-bold">سفارش‌ها و پرداخت‌ها</h2><table className="table"><thead><tr><th>شماره</th><th>نوع</th><th>وضعیت</th><th>مبلغ</th><th>زمان</th></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td dir="ltr">{order.number}</td><td>{order.kind}</td><td>{order.status}</td><td>{fmt.toman(order.amount_toman)}</td><td>{fmt.dateTime(order.created_at)}</td></tr>)}</tbody></table><Pagination page={Math.floor(orderOffset/limit)+1} hasPrevious={orderOffset>0} hasNext={orderOffset+limit<orderTotal} total={orderTotal} onPrevious={()=>setOrderOffset(Math.max(0,orderOffset-limit))} onNext={()=>setOrderOffset(orderOffset+limit)}/></div>
      ) : null}

      <div className="card">
        <h2 className="mb-2 font-bold">آخرین تراکنش‌ها</h2>
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
                  <td>{LEDGER_LABELS[entry.kind] ?? entry.kind}</td>
                  <td dir="ltr">{fmt.int(entry.seconds_delta)}</td>
                  <td dir="ltr">{fmt.int(entry.toman_delta)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <Pagination page={Math.floor(ledgerOffset/limit)+1} hasPrevious={ledgerOffset>0} hasNext={ledgerOffset+limit<ledgerTotal} total={ledgerTotal} onPrevious={()=>setLedgerOffset(Math.max(0,ledgerOffset-limit))} onNext={()=>setLedgerOffset(ledgerOffset+limit)}/>
      </div>

      {isAdmin ? (
        <>
          <ApiKeyManager keys={keys} reload={reload} />
          <Pagination page={Math.floor(keyOffset/limit)+1} hasPrevious={keyOffset>0} hasNext={keyOffset+limit<keyTotal} total={keyTotal} onPrevious={()=>setKeyOffset(Math.max(0,keyOffset-limit))} onNext={()=>setKeyOffset(keyOffset+limit)}/>

          <div className="card">
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className="font-bold">کاربران</h2>
              {maxOperators == null ? null : (
                <span className="text-xs text-slate-400">
                  اپراتور {fmt.int(users.filter((user) => user.role === "operator").length)} از{" "}
                  {fmt.int(maxOperators)}
                </span>
              )}
            </div>
            <table className="table mb-3">
              <thead>
                <tr>
                  <th>ایمیل</th>
                  <th>نقش</th>
                  <th>موبایل</th>
                  <th>داخلی</th>
                  <th>ایجاد</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <tr key={user.id}>
                    <td dir="ltr">{user.email}</td>
                    <td>{ROLE_LABELS[user.role] ?? user.role}</td>
                    <td dir="ltr">{user.mobile_number ? fmt.digits(user.mobile_number) : "—"}</td>
                    <td dir="ltr">{user.extension ? fmt.digits(user.extension) : "—"}</td>
                    <td>{fmt.date(user.created_at)}</td>
                    <td>
                      {user.id === session?.userId ? null : (
                        <button
                          className="btn-ghost text-xs"
                          onClick={async () => {
                            await request<void>(`/v1/auth/users/${user.id}`, { method: "DELETE" });
                            await reload();
                          }}
                        >
                          حذف
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination page={Math.floor(userOffset/limit)+1} hasPrevious={userOffset>0} hasNext={userOffset+limit<userTotal} total={userTotal} onPrevious={()=>setUserOffset(Math.max(0,userOffset-limit))} onNext={()=>setUserOffset(userOffset+limit)}/>
            <form className="grid gap-2 md:grid-cols-4" onSubmit={createUser}>
              <input
                className="input"
                type="email"
                dir="ltr"
                placeholder="ایمیل"
                value={userForm.email}
                onChange={(event) => setUserForm({ ...userForm, email: event.target.value })}
                required
              />
              <input
                className="input"
                type="password"
                dir="ltr"
                placeholder="گذرواژه (حداقل ۸)"
                value={userForm.password}
                onChange={(event) => setUserForm({ ...userForm, password: event.target.value })}
                minLength={8}
                required
              />
              <select
                className="input"
                value={userForm.role}
                onChange={(event) => setUserForm({ ...userForm, role: event.target.value })}
              >
                <option value="org_admin">مدیر سازمان</option>
                <option value="operator">اپراتور</option>
                <option value="viewer">بیننده</option>
              </select>
              <button className="btn">افزودن کاربر</button>
              {userForm.role === "operator" ? (
                <>
                  <input
                    className="input"
                    dir="ltr"
                    inputMode="tel"
                    placeholder="شماره موبایل اپراتور"
                    value={userForm.mobile_number}
                    onChange={(event) =>
                      setUserForm({ ...userForm, mobile_number: event.target.value })
                    }
                  />
                  <input
                    className="input"
                    dir="ltr"
                    inputMode="numeric"
                    placeholder="شماره داخلی"
                    value={userForm.extension}
                    onChange={(event) =>
                      setUserForm({ ...userForm, extension: event.target.value })
                    }
                  />
                  <p className="text-xs text-slate-400 md:col-span-2">
                    برای اپراتور حداقل یکی از شماره موبایل یا شماره داخلی لازم است. اپراتور فقط
                    تماس‌هایی را می‌بیند که خودش یک سمت آن باشد.
                  </p>
                </>
              ) : null}
            </form>
          </div>

          <div className="card">
            <h2 className="mb-2 font-bold">وب‌هوک‌ها</h2>
            {hookSecret ? (
              <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
                <div className="mb-1 font-medium">کلید امضا (فقط یک بار):</div>
                <code dir="ltr" className="break-all">
                  {hookSecret}
                </code>
                <div className="mt-1 text-xs text-slate-500">
                  امضا: sha256=HMAC(secret, «timestamp.body») در هدر X-CBI-Signature
                </div>
              </div>
            ) : null}
            <table className="table mb-3">
              <thead>
                <tr>
                  <th>آدرس</th>
                  <th>رویدادها</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {hooks.map((hook) => (
                  <tr key={hook.id}>
                    <td dir="ltr" className="max-w-sm truncate">
                      {hook.url}
                    </td>
                    <td dir="ltr">{hook.events.join(", ")}</td>
                    <td>
                      <button
                        className="btn-ghost text-xs"
                        onClick={async () => {
                          await request<void>(`/v1/webhooks/${hook.id}`, { method: "DELETE" });
                          await reload();
                        }}
                      >
                        حذف
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination page={Math.floor(hookOffset/limit)+1} hasPrevious={hookOffset>0} hasNext={hookOffset+limit<hookTotal} total={hookTotal} onPrevious={()=>setHookOffset(Math.max(0,hookOffset-limit))} onNext={()=>setHookOffset(hookOffset+limit)}/>
            <form className="grid gap-2 md:grid-cols-3" onSubmit={createHook}>
              <input
                className="input md:col-span-2"
                dir="ltr"
                placeholder="https://example.com/hook"
                value={hookForm.url}
                onChange={(event) => setHookForm({ ...hookForm, url: event.target.value })}
                required
              />
              <button className="btn">افزودن</button>
              <div className="md:col-span-3 flex flex-wrap gap-3 text-sm">
                {EVENTS.map((event) => (
                  <ToggleSwitch
                      key={event}
                      dir="ltr"
                      checked={hookForm.events.includes(event)}
                      onChange={(checked) =>
                        setHookForm({
                          ...hookForm,
                          events: checked
                            ? [...hookForm.events, event]
                            : hookForm.events.filter((item) => item !== event),
                        })
                      }
                      label={EVENT_LABELS[event] ?? event}
                    />
                ))}
              </div>
            </form>
          </div>

          <div className="card">
            <h2 className="mb-2 font-bold">داده‌های سازمان</h2>
            <div className="flex flex-wrap gap-2">
              <button className="btn-ghost" onClick={() => void download("json")}>
                خروجی JSON
              </button>
              <button className="btn-ghost" onClick={() => void download("csv")}>
                خروجی CSV
              </button>
              <button
                className="btn-ghost border-rose-300 text-rose-700"
                onClick={async () => {
                  if (!window.confirm("همه تماس‌ها، متن‌ها و فایل‌های صوتی حذف می‌شوند. مطمئن هستید؟"))
                    return;
                  await request<void>("/v1/account/data", { method: "DELETE" });
                  await reload();
                }}
              >
                حذف کامل داده‌ها
              </button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
