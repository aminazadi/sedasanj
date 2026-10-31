import { Icon } from "@iconify/react";
import walletIcon from "@iconify-icons/lucide/wallet";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import { ROLE_LABELS, useAuth } from "../auth";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
import ApiKeyManager from "../components/ApiKeyManager";
import WebhookDeliveries from "../components/WebhookDeliveries";
import CreditTopUp from "../components/CreditTopUp";
import OrderPaymentPanel from "../components/OrderPaymentPanel";
import SubscriptionPanel from "../components/SubscriptionPanel";
import ConfirmDialog from "../components/ConfirmDialog";
import FormDialog from "../components/FormDialog";
import addUserArt from "../assets/add-user.webp";
import type {
  AccountInfo,
  ApiKey,
  Balance,
  LedgerEntry,
  Package,
  Page,
  SubscriptionInfo,
  User,
  Webhook,
  WebhookCreated,
  WebhookTestResult,
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

const ORDER_KIND_LABELS: Record<string, string> = {
  subscription: "اشتراک",
  credit: "خرید اعتبار",
  credit_purchase: "خرید اعتبار",
  installation: "نصب و استقرار",
  operator_addon: "اپراتور اضافه",
  subscription_upgrade: "ارتقای اشتراک",
  renewal: "تمدید اشتراک",
};

const ORDER_STATUS_LABELS: Record<string, string> = {
  draft: "پیش‌نویس",
  pending_payment: "در انتظار پرداخت",
  paid: "پرداخت‌شده",
  canceled: "لغوشده",
  partially_refunded: "بازپرداخت جزئی",
  refunded: "بازپرداخت‌شده",
};

const EMPTY_USER = {
  email: "",
  password: "",
  role: "operator",
  mobile_number: "",
  extension: "",
};

function offsetParam(params: URLSearchParams, name: string): number {
  const value = Number(params.get(name));
  return Number.isInteger(value) && value > 0 ? value : 0;
}

function withOffset(params: URLSearchParams, name: string, value: number): URLSearchParams {
  const next = new URLSearchParams(params);
  if (value > 0) next.set(name, String(value));
  else next.delete(name);
  return next;
}

export type AccountSection = "billing" | "users" | "integrations" | "data";

export default function Account({ section = "billing" }: { section?: AccountSection }) {
  const limit = 10;
  const { session } = useAuth();
  const isAdmin = session?.role === "org_admin";

  const [balance, setBalance] = useState<Balance | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [packages, setPackages] = useState<Package[]>([]);
  const [payingOrder, setPayingOrder] = useState<{ id: string; amount: number } | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [maxOperators, setMaxOperators] = useState<number | null>(null);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [hookNote, setHookNote] = useState<string | null>(null);
  const [logHookId, setLogHookId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [hookSecret, setHookSecret] = useState<string | null>(null);
  const [dataDeletionOpen, setDataDeletionOpen] = useState(false);
  const [dataDeleting, setDataDeleting] = useState(false);
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [orders, setOrders] = useState<Array<{ id: string; number: string; kind: string; status: string; amount_toman: number; created_at: string }>>([]);
  const [params, setParams] = useSearchParams();
  const ledgerOffset = offsetParam(params, "ledger");
  const orderOffset = offsetParam(params, "orders");
  const setLedgerOffset = (value: number) => setParams(withOffset(params, "ledger", value), { replace: true });
  const setOrderOffset = (value: number) => setParams(withOffset(params, "orders", value), { replace: true });
  const [ledgerTotal, setLedgerTotal] = useState(0);
  const [orderTotal, setOrderTotal] = useState(0);
  const [userOffset, setUserOffset] = useState(0);
  const [userTotal, setUserTotal] = useState(0);
  const [keyOffset, setKeyOffset] = useState(0);
  const [keyTotal, setKeyTotal] = useState(0);
  const [hookOffset, setHookOffset] = useState(0);
  const [hookTotal, setHookTotal] = useState(0);

  const [userForm, setUserForm] = useState(EMPTY_USER);
  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [userDialogBusy, setUserDialogBusy] = useState(false);
  const [userDialogError, setUserDialogError] = useState<string | null>(null);
  const [hookForm, setHookForm] = useState({ url: "", events: ["call.complete"] as string[] });

  async function deleteAccountData() {
    setDataDeleting(true);
    setError(null);
    try {
      await request<void>("/v1/account/data", { method: "DELETE" });
      setDataDeletionOpen(false);
      await reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setDataDeleting(false);
    }
  }

  async function reload() {
    setError(null);
    try {
      if (section === "billing") {
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
          const [subscriptionData, orderData] = await Promise.all([
            request<SubscriptionInfo>("/v1/subscription"),
            request<Page<{ id: string; number: string; kind: string; status: string; amount_toman: number; created_at: string }>>(`/v1/orders?limit=${limit}&offset=${orderOffset}`),
          ]);
          setSubscription(subscriptionData);
          setOrders(orderData.items);
          setOrderTotal(orderData.total);
        }
      } else if (section === "users") {
        const [usersData, account] = await Promise.all([
          request<Page<User>>(`/v1/auth/users?limit=${limit}&offset=${userOffset}`),
          request<AccountInfo>("/v1/account"),
        ]);
        setUsers(usersData.items);
        setUserTotal(usersData.total);
        setMaxOperators(account.tenant.max_operators);
      } else if (section === "integrations") {
        const [keysData, hooksData] = await Promise.all([
          request<Page<ApiKey>>(`/v1/auth/api-keys?limit=${limit}&offset=${keyOffset}`),
          request<Page<Webhook>>(`/v1/webhooks?limit=${limit}&offset=${hookOffset}`),
        ]);
        setKeys(keysData.items);
        setKeyTotal(keysData.total);
        setHooks(hooksData.items);
        setHookTotal(hooksData.total);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, [hookOffset, isAdmin, keyOffset, ledgerOffset, orderOffset, section, userOffset]);

  async function createUser() {
    setUserDialogBusy(true);
    setUserDialogError(null);
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
      setUserDialogOpen(false);
      await reload();
    } catch (err) {
      setUserDialogError((err as Error).message);
    } finally {
      setUserDialogBusy(false);
    }
  }

  async function testHook(hook: Webhook) {
    try {
      const result = await request<WebhookTestResult>(`/v1/webhooks/${hook.id}/test`, { method: "POST" });
      setHookNote(result.ok ? `تست موفق بود (${result.delivery.status_code ?? "—"}).` : `تست ناموفق بود: ${result.delivery.error ?? ""}`);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function rotateHook(hook: Webhook) {
    try {
      const rotated = await request<WebhookCreated>(`/v1/webhooks/${hook.id}/rotate-secret`, { method: "POST" });
      setHookSecret(rotated.secret);
      setHookNote("کلید قبلی تا ۲۴ ساعت در هدر X-CBI-Signature-Previous هم امضا می‌شود.");
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function toggleHook(hook: Webhook) {
    try {
      await request<Webhook>(`/v1/webhooks/${hook.id}`, { method: "PATCH", body: { active: !hook.active } });
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

  if (loading || (section === "billing" && !balance && !error)) return <Loading />;
  if (section === "billing" && !balance) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {section === "billing" ? <PageHeader title="اعتبار و اشتراک" description="اعتبار، پلن فعال و صورتحساب‌های سازمان" /> : null}
      <ErrorBox message={error} />

      {section === "billing" && balance ? <>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="card">
          <h2 className="font-bold">اعتبار</h2>
          <div className="flex items-center gap-4">
            <span className="flex h-14 w-14 shrink-0 items-center justify-center bg-[#4B6E48] text-[#F2F0EF]" aria-hidden="true"><Icon icon={walletIcon} className="h-7 w-7" /></span>
            <div className="min-w-0">
              <div className="text-xs text-slate-500">موجودی فعلی</div>
              <div className="text-2xl font-extrabold tracking-tight text-[#4B6E48]">{fmt.toman(balance.toman)}</div>
              <div className="text-sm text-slate-500">{fmt.int(balance.minutes)} دقیقه باقی‌مانده</div>
            </div>
          </div>
          {(() => {
            const total = balance.expiring_seconds + balance.purchased_seconds;
            const planShare = total > 0 ? (balance.expiring_seconds / total) * 100 : 0;
            return <div className="mt-5" role="img" aria-label="سهم دقیقه‌های رایگان پلن و اعتبار پیش‌خریدی">
              <div className="flex h-2.5 w-full overflow-hidden bg-[color:var(--line)]">
                <span className="h-full bg-[#B2AC88]" style={{ width: `${planShare}%` }} />
                <span className="h-full bg-[#4B6E48]" style={{ width: `${total > 0 ? 100 - planShare : 0}%` }} />
              </div>
            </div>;
          })()}
          <dl className="mt-4 space-y-2.5 text-sm">
            <div className="flex items-center justify-between gap-3"><dt className="flex items-center gap-2"><span className="h-2.5 w-2.5 bg-[#B2AC88]" aria-hidden="true" />دقیقه رایگان پلن</dt><dd className="font-medium">{fmt.minutes(balance.expiring_seconds)}</dd></div>
            <div className="flex items-center justify-between gap-3"><dt className="flex items-center gap-2"><span className="h-2.5 w-2.5 bg-[#4B6E48]" aria-hidden="true" />اعتبار پیش‌خریدی</dt><dd className="font-medium">{fmt.minutes(balance.purchased_seconds)}</dd></div>
            <div className="flex items-center justify-between gap-3 border-t border-[color:var(--line)] pt-2.5"><dt className="text-slate-500">نرخ هر دقیقه</dt><dd className="font-medium">{fmt.toman(balance.price_per_minute_toman)}</dd></div>
          </dl>
        </div>
        <div className="card md:col-span-2">
          <h2 className="mb-3 font-bold">شارژ اعتبار تحلیل</h2>
          {isAdmin ? (
            <CreditTopUp packages={packages} pricePerMinute={balance.price_per_minute_toman} onError={setError} />
          ) : (
            <p className="text-sm text-slate-500">خرید اعتبار فقط برای مدیر سازمان در دسترس است.</p>
          )}
        </div>
      </div>

      {isAdmin && subscription ? <SubscriptionPanel subscription={subscription} onChanged={reload} onError={setError} /> : null}

      {isAdmin && orders.length ? (
        <>{payingOrder ? <OrderPaymentPanel orderId={payingOrder.id} amountToman={payingOrder.amount} onClose={() => setPayingOrder(null)} onError={setError} /> : null}<div className="card"><h2 className="mb-2 font-bold">سفارش‌ها و پرداخت‌ها</h2><table className="table"><thead><tr><th>شماره</th><th>نوع</th><th>وضعیت</th><th>مبلغ</th><th>زمان</th><th /></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td dir="ltr">{order.number}</td><td>{ORDER_KIND_LABELS[order.kind] ?? order.kind}</td><td>{ORDER_STATUS_LABELS[order.status] ?? order.status}</td><td>{fmt.toman(order.amount_toman)}</td><td>{fmt.dateTime(order.created_at)}</td><td>{["draft", "pending_payment"].includes(order.status) ? <button className="btn-ghost text-xs" onClick={() => setPayingOrder({ id: order.id, amount: order.amount_toman })}>پرداخت</button> : null}</td></tr>)}</tbody></table><Pagination page={Math.floor(orderOffset/limit)+1} hasPrevious={orderOffset>0} hasNext={orderOffset+limit<orderTotal} total={orderTotal} onPrevious={()=>setOrderOffset(Math.max(0,orderOffset-limit))} onNext={()=>setOrderOffset(orderOffset+limit)}/></div></>
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
      </> : null}

      {isAdmin && section !== "billing" ? (
        <>
          {section === "integrations" ? <>
          <ApiKeyManager keys={keys} reload={reload} />
          <Pagination page={Math.floor(keyOffset/limit)+1} hasPrevious={keyOffset>0} hasNext={keyOffset+limit<keyTotal} total={keyTotal} onPrevious={()=>setKeyOffset(Math.max(0,keyOffset-limit))} onNext={()=>setKeyOffset(keyOffset+limit)}/>
          </> : null}

          {section === "users" ? <>
          <div className="card">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-bold">کاربران</h2>
              <div className="flex items-center gap-3">
                {maxOperators == null ? null : (
                  <span className="field-hint !mt-0">
                    اپراتور {fmt.int(users.filter((user) => user.role === "operator").length)} از{" "}
                    {fmt.int(maxOperators)}
                  </span>
                )}
                <button className="btn" type="button" onClick={() => { setUserDialogError(null); setUserDialogOpen(true); }}>افزودن کاربر</button>
              </div>
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
                          className="btn-danger"
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
          </div>
          </> : null}

          {section === "integrations" ? <>
          <div className="card">
            <h2 className="mb-2 font-bold">وب‌هوک‌ها</h2>
            {hookSecret ? (
              <div className="mb-3 border border-amber-200 bg-amber-50 p-3 text-sm">
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
                  <th>وضعیت</th>
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
                    <td>{hook.active ? "فعال" : hook.disabled_reason === "consecutive_failures" ? "غیرفعال (شکست پیاپی)" : "غیرفعال"}</td>
                    <td className="space-x-1 space-x-reverse whitespace-nowrap">
                      <button className="btn-ghost text-xs" onClick={() => void testHook(hook)}>تست</button>
                      <button className="btn-ghost text-xs" onClick={() => setLogHookId(logHookId === hook.id ? null : hook.id)}>لاگ</button>
                      <button className="btn-ghost text-xs" onClick={() => void rotateHook(hook)}>چرخش کلید</button>
                      <button className="btn-ghost text-xs" onClick={() => void toggleHook(hook)}>{hook.active ? "غیرفعال‌سازی" : "فعال‌سازی"}</button>
                      <button
                        className="btn-danger"
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
            {hookNote ? <div className="mb-2 text-sm text-slate-600">{hookNote}</div> : null}
            {logHookId ? <WebhookDeliveries webhookId={logHookId} onClose={() => setLogHookId(null)} /> : null}
            <Pagination page={Math.floor(hookOffset/limit)+1} hasPrevious={hookOffset>0} hasNext={hookOffset+limit<hookTotal} total={hookTotal} onPrevious={()=>setHookOffset(Math.max(0,hookOffset-limit))} onNext={()=>setHookOffset(hookOffset+limit)}/>
            <form className="grid gap-2 md:grid-cols-3" onSubmit={createHook}>
              <input
                className="input md:col-span-2"
                dir="ltr"
                aria-label="آدرس وب‌هوک"
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
          </> : null}

          {section === "data" ? <>
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
                className="btn-danger"
                onClick={() => setDataDeletionOpen(true)}
              >
                حذف کامل داده‌ها
              </button>
            </div>
          </div>
          </> : null}
        </>
      ) : null}
      <FormDialog open={userDialogOpen} title="افزودن کاربر" description="کاربر جدید با ایمیل و گذرواژهٔ موقت وارد پنل می‌شود." art={addUserArt} submitLabel="افزودن کاربر" busy={userDialogBusy} error={userDialogError} onClose={() => setUserDialogOpen(false)} onSubmit={() => void createUser()}>
        <label><span>ایمیل</span><input type="email" dir="ltr" value={userForm.email} onChange={(event) => setUserForm({ ...userForm, email: event.target.value })} required /></label>
        <label><span>گذرواژه (حداقل ۸ نویسه)</span><input type="password" dir="ltr" value={userForm.password} onChange={(event) => setUserForm({ ...userForm, password: event.target.value })} minLength={8} required /></label>
        <label><span>نقش</span><select value={userForm.role} onChange={(event) => setUserForm({ ...userForm, role: event.target.value })}><option value="org_admin">مدیر سازمان</option><option value="operator">اپراتور</option><option value="viewer">بیننده</option></select></label>
        {userForm.role === "operator" ? <>
          <label><span>شماره موبایل اپراتور</span><input dir="ltr" inputMode="tel" value={userForm.mobile_number} onChange={(event) => setUserForm({ ...userForm, mobile_number: event.target.value })} /></label>
          <label><span>شماره داخلی</span><input dir="ltr" inputMode="numeric" value={userForm.extension} onChange={(event) => setUserForm({ ...userForm, extension: event.target.value })} /></label>
          <p>برای اپراتور حداقل یکی از شماره موبایل یا شماره داخلی لازم است. اپراتور فقط تماس‌هایی را می‌بیند که خودش یک سمت آن باشد.</p>
        </> : null}
      </FormDialog>
      <ConfirmDialog
        open={dataDeletionOpen}
        title="حذف کامل داده‌ها"
        description="همه تماس‌ها، متن‌ها، تحلیل‌ها، کارهای مرتبط و فایل‌های صوتی برای همیشه حذف می‌شوند. این عملیات قابل بازگشت نیست."
        confirmLabel="حذف کامل داده‌ها"
        destructive
        busy={dataDeleting}
        onCancel={() => setDataDeletionOpen(false)}
        onConfirm={() => void deleteAccountData()}
      />
    </div>
  );
}
