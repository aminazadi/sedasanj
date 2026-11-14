import { useTablePageSize, useTableOffset } from "../lib/useTablePagination";
import { Icon } from "@iconify/react";
import walletIcon from "@iconify-icons/lucide/wallet";
import webhookIcon from "@iconify-icons/lucide/webhook";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import { ROLE_LABELS, useAuth } from "../auth";
import { ErrorBox, Loading, Pagination } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
import ApiKeyManager from "../components/ApiKeyManager";
import WebhookDeliveries from "../components/WebhookDeliveries";
import CreditTopUp from "../components/CreditTopUp";
import { usageShares } from "../lib/creditUsage.mjs";
import OrderPaymentPanel from "../components/OrderPaymentPanel";
import SubscriptionPanel from "../components/SubscriptionPanel";
import TokenTopUp from "../components/TokenTopUp";
import DocumentTabs from "../components/DocumentTabs";
import EditOrganizationUser from "../components/EditOrganizationUser";
import OperatorExtensionInput from "../components/OperatorExtensionInput";
import PanelAccessEditor from "../components/PanelAccessEditor";
import FormDialog from "../components/FormDialog";
import addUserArt from "../assets/add-user.webp";
import type {
  AccountInfo,
  ApiKey,
  Balance,
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

const ORDER_KIND_LABELS: Record<string, string> = {
  subscription: "اشتراک",
  credit: "خرید اعتبار",
  credit_purchase: "خرید اعتبار",
  installation: "نصب و استقرار",
  operator_addon: "اپراتور اضافه",
  subscription_upgrade: "ارتقای اشتراک",
  renewal: "تمدید اشتراک",
  token_pack: "بسته توکن هوش مصنوعی",
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
  panel_permissions: null as string[] | null,
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

export type AccountSection = "billing" | "users" | "integrations";

export default function Account({ section = "billing" }: { section?: AccountSection }) {
  const [limit] = useTablePageSize();
  const { session } = useAuth();
  const isAdmin = session?.role === "org_admin";

  const [kind, setKind] = useState<"asr" | "llm">("asr");
  const [balance, setBalance] = useState<Balance | null>(null);
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
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [orders, setOrders] = useState<Array<{ id: string; number: string; kind: string; status: string; amount_toman: number; created_at: string }>>([]);
  const [params, setParams] = useSearchParams();
  const editingUserId = params.get("edit_user");
  function selectEditedUser(id: string | null) {
    const next = new URLSearchParams(params);
    if (id) next.set("edit_user", id);
    else next.delete("edit_user");
    setParams(next);
  }

  const orderOffset = offsetParam(params, "orders");
  const setOrderOffset = (value: number) => setParams(withOffset(params, "orders", value), { replace: true });
  const [orderTotal, setOrderTotal] = useState(0);
  const [userOffset, setUserOffset] = useTableOffset("user_offset");
  const [userTotal, setUserTotal] = useState(0);
  const [keyOffset, setKeyOffset] = useTableOffset("key_offset");
  const [keyTotal, setKeyTotal] = useState(0);
  const [hookOffset, setHookOffset] = useTableOffset("hook_offset");
  const [hookTotal, setHookTotal] = useState(0);

  const [userForm, setUserForm] = useState(EMPTY_USER);
  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [userDialogBusy, setUserDialogBusy] = useState(false);
  const [userDialogError, setUserDialogError] = useState<string | null>(null);
  const [hookForm, setHookForm] = useState({ url: "", events: ["call.complete"] as string[] });

  async function reload() {
    setError(null);
    try {
      if (section === "billing") {
        const [balanceData, packagesData] = await Promise.all([
          request<Balance>("/v1/billing/balance"),
          request<Package[]>("/v1/billing/packages"),
        ]);
        setBalance(balanceData);
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
  }, [limit, hookOffset, isAdmin, keyOffset, orderOffset, section, userOffset]);

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

  if (loading || (section === "billing" && !balance && !error)) return <Loading />;
  if (section === "billing" && !balance) return <ErrorBox message={error} />;

  return (
    <div className="space-y-4">
      {section === "billing" ? <PageHeader title="اعتبار و اشتراک" description="اعتبار، پلن فعال و صورتحساب‌های سازمان" actions={<Link className="btn-ghost" to="/account/transactions">مشاهدهٔ تراکنش‌ها</Link>} /> : null}
      <ErrorBox message={error} />

      {section === "billing" && balance ? <>
      {isAdmin && subscription ? <SubscriptionPanel subscription={subscription} onChanged={reload} onError={setError} /> : null}
      <div className="grid gap-4 md:grid-cols-3">
        <div className="card credit-card credit-balance">
          <h2 className="credit-title">اعتبار</h2>
          {(() => {
            const shares = usageShares(balance.expiring_seconds, balance.purchased_seconds);
            return <>
              <div className="credit-hero">
                <span className="credit-hero-icon" aria-hidden="true"><Icon icon={walletIcon} className="h-7 w-7" /></span>
                <div className="min-w-0">
                  <div className="credit-hero-label">موجودی فعلی</div>
                  <div className="credit-hero-amount">{fmt.toman(balance.toman)}</div>
                  <div className="credit-hero-minutes">{fmt.int(balance.minutes)} دقیقه باقی‌مانده</div>
                </div>
              </div>
              <div className={`credit-bar${shares.empty ? " is-empty" : ""}`} role="img" aria-label="سهم دقیقه‌های رایگان پلن و اعتبار پیش‌خریدی">
                <span className="credit-bar-plan" style={{ width: `${shares.plan}%` }} />
                <span className="credit-bar-paid" style={{ width: `${shares.purchased}%` }} />
              </div>
              {shares.empty ? <p className="credit-empty-hint">هنوز دقیقه‌ای ندارید؛ از کارت کناری شارژ کنید.</p> : null}
              <dl className="credit-legend">
                <div><dt><span className="credit-dot is-plan" aria-hidden="true" />دقیقه رایگان پلن</dt><dd>{fmt.minutes(balance.expiring_seconds)}{shares.empty ? null : <small>{fmt.digits(Math.round(shares.plan))}٪</small>}</dd></div>
                <div><dt><span className="credit-dot is-paid" aria-hidden="true" />اعتبار پیش‌خریدی</dt><dd>{fmt.minutes(balance.purchased_seconds)}{shares.empty ? null : <small>{fmt.digits(Math.round(shares.purchased))}٪</small>}</dd></div>
                <div className="credit-rate"><dt>نرخ هر دقیقه</dt><dd>{fmt.toman(balance.price_per_minute_toman)}</dd></div>
                {isAdmin && subscription ? <div className="credit-rate credit-tokens"><dt>توکن هوش مصنوعی</dt><dd>{subscription.llm_tokens_unlimited ? "نامحدود" : <>{fmt.int(subscription.llm_tokens_remaining ?? 0)}<small>{subscription.llm_tokens_topup_remaining ? `شامل ${fmt.int(subscription.llm_tokens_topup_remaining)} از بسته` : "باقی‌مانده"}</small></>}</dd></div> : null}
              </dl>
            </>;
          })()}
        </div>
        <div className="card credit-card md:col-span-2">
          <h2 className="credit-title">شارژ اعتبار تحلیل</h2>
          {isAdmin ? (
            <>
              {subscription ? (
                <DocumentTabs
                  value={kind}
                  onChange={setKind}
                  label="نوع اعتبار"
                  align="start"
                  options={[
                    { value: "asr", label: "دقیقهٔ تحلیل گفتار" },
                    { value: "llm", label: "توکن هوش مصنوعی" },
                  ]}
                />
              ) : null}
              {kind === "llm" && subscription ? (
                subscription.llm_tokens_unlimited ? (
                  <p className="credit-empty-hint">پلن شما توکن هوش مصنوعی نامحدود دارد و نیازی به خرید بسته نیست.</p>
                ) : (
                  <TokenTopUp embedded onError={setError} />
                )
              ) : (
                <CreditTopUp packages={packages} pricePerMinute={balance.price_per_minute_toman} onError={setError} />
              )}
            </>
          ) : (
            <p className="text-sm text-slate-500">خرید اعتبار فقط برای مدیر سازمان در دسترس است.</p>
          )}
        </div>
      </div>


      {isAdmin && orders.length ? (
        <>{payingOrder ? <OrderPaymentPanel orderId={payingOrder.id} amountToman={payingOrder.amount} onClose={() => setPayingOrder(null)} onError={setError} /> : null}<div className="card"><h2 className="mb-2 font-bold">سفارش‌ها و پرداخت‌ها</h2><table className="table"><thead><tr><th>شماره</th><th>نوع</th><th>وضعیت</th><th>مبلغ</th><th>زمان</th><th /></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td dir="ltr">{order.number}</td><td>{ORDER_KIND_LABELS[order.kind] ?? order.kind}</td><td>{ORDER_STATUS_LABELS[order.status] ?? order.status}</td><td>{fmt.toman(order.amount_toman)}</td><td>{fmt.dateTime(order.created_at)}</td><td>{["draft", "pending_payment"].includes(order.status) ? <button className="btn-ghost text-xs" onClick={() => setPayingOrder({ id: order.id, amount: order.amount_toman })}>پرداخت</button> : null}</td></tr>)}</tbody></table><Pagination page={Math.floor(orderOffset/limit)+1} hasPrevious={orderOffset>0} hasNext={orderOffset+limit<orderTotal} total={orderTotal} onPrevious={()=>setOrderOffset(Math.max(0,orderOffset-limit))} onNext={()=>setOrderOffset(orderOffset+limit)}/></div></>
      ) : null}

      </> : null}

      {isAdmin && section !== "billing" ? (
        <>
          {section === "integrations" ? <>
          <ApiKeyManager keys={keys} reload={reload} />
          {keyTotal > limit || keyOffset > 0 ? <Pagination page={Math.floor(keyOffset/limit)+1} hasPrevious={keyOffset>0} hasNext={keyOffset+limit<keyTotal} total={keyTotal} onPrevious={()=>setKeyOffset(Math.max(0,keyOffset-limit))} onNext={()=>setKeyOffset(keyOffset+limit)}/> : null}
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
                    <td>{user.is_primary_admin ? "مدیر اصلی سازمان" : ROLE_LABELS[user.role] ?? user.role}</td>
                    <td dir="ltr">{user.mobile_number ? fmt.digits(user.mobile_number) : "—"}</td>
                    <td dir="ltr">{user.extension ? fmt.digits(user.extension) : "—"}</td>
                    <td>{fmt.date(user.created_at)}</td>
                    <td>
                      {user.id === session?.userId ? null : (
                        <>
                        <button className="btn-ghost" type="button" onClick={() => selectEditedUser(user.id)}>
                          ویرایش
                        </button>
                        <button
                          className="btn-danger"
                          disabled={user.is_primary_admin}
                          onClick={async () => {
                            await request<void>(`/v1/auth/users/${user.id}`, { method: "DELETE" });
                            await reload();
                          }}
                        >
                          حذف
                        </button>
                        </>
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
          <div className="card integ-card space-y-4">
            <div>
              <h2 className="font-bold">وب‌هوک‌ها</h2>
              <p className="section-hint">رویدادهای انتخاب‌شده با درخواست امضادار به آدرس‌های زیر ارسال می‌شود.</p>
            </div>
            {hookSecret ? (
              <div className="integ-secret p-3 text-sm">
                <div className="mb-1 font-medium">کلید امضا (فقط یک بار):</div>
                <code dir="ltr" className="break-all">
                  {hookSecret}
                </code>
                <div className="mt-1 text-xs text-slate-500">
                  امضا: sha256=HMAC(secret, «timestamp.body») در هدر X-CBI-Signature
                </div>
              </div>
            ) : null}
            {hooks.length === 0 ? (
              <div className="integ-empty">
                <span className="integ-empty-icon" aria-hidden="true"><Icon icon={webhookIcon} className="h-5 w-5" /></span>
                <div><strong>هنوز وب‌هوکی ثبت نشده است</strong><p>از فرم «افزودن وب‌هوک» پایین همین صفحه یک آدرس اضافه کنید.</p></div>
              </div>
            ) : <div className="overflow-x-auto"><table className="table">
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
            </table></div>}
            {hookNote ? <div className="mb-2 text-sm text-slate-600">{hookNote}</div> : null}
            {logHookId ? <WebhookDeliveries webhookId={logHookId} onClose={() => setLogHookId(null)} /> : null}
            {hookTotal > limit || hookOffset > 0 ? <Pagination page={Math.floor(hookOffset/limit)+1} hasPrevious={hookOffset>0} hasNext={hookOffset+limit<hookTotal} total={hookTotal} onPrevious={()=>setHookOffset(Math.max(0,hookOffset-limit))} onNext={()=>setHookOffset(hookOffset+limit)}/> : null}
          </div>
          <form className="key-form" onSubmit={createHook}>
            <h3 className="key-form-title">افزودن وب‌هوک</h3>
            <section className="key-step">
              <span className="key-step-n" aria-hidden="true">1</span>
              <div className="key-step-body">
                <h4>آدرس دریافت‌کننده</h4>
                <input
                  className="input"
                  dir="ltr"
                  aria-label="آدرس وب‌هوک"
                  placeholder="https://example.com/hook"
                  value={hookForm.url}
                  onChange={(event) => setHookForm({ ...hookForm, url: event.target.value })}
                  required
                />
              </div>
            </section>
            <section className="key-step">
              <span className="key-step-n" aria-hidden="true">2</span>
              <div className="key-step-body">
                <h4>رویدادها</h4>
                <div className="scope-grid">
                  {EVENTS.map((event) => {
                    const on = hookForm.events.includes(event);
                    return (
                      <div key={event} className={`scope-tile${on ? " is-on" : ""}`}>
                        <ToggleSwitch
                          dir="ltr"
                          checked={on}
                          onChange={(checked) =>
                            setHookForm({
                              ...hookForm,
                              events: checked ? [...hookForm.events, event] : hookForm.events.filter((item) => item !== event),
                            })
                          }
                          label={EVENT_LABELS[event] ?? event}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
            <div className="key-form-foot">
              <p>{hookForm.events.length === 0 ? "حداقل یک رویداد انتخاب کنید." : `${hookForm.events.length} رویداد انتخاب شده است.`}</p>
              <button className="btn" disabled={hookForm.events.length === 0}>افزودن وب‌هوک</button>
            </div>
          </form>
          </> : null}

        </>
      ) : null}
      {section === "users" && isAdmin && editingUserId && editingUserId !== session?.userId ? (
        <EditOrganizationUser
          key={editingUserId}
          userId={editingUserId}
          onClose={() => selectEditedUser(null)}
          onSaved={reload}
        />
      ) : null}
      <FormDialog open={userDialogOpen} wide title="افزودن کاربر" description="کاربر جدید با ایمیل و گذرواژهٔ موقت وارد پنل می‌شود." art={addUserArt} submitLabel="افزودن کاربر" busy={userDialogBusy} error={userDialogError} onClose={() => setUserDialogOpen(false)} onSubmit={() => void createUser()}>
        <label><span>ایمیل</span><input type="email" dir="ltr" value={userForm.email} onChange={(event) => setUserForm({ ...userForm, email: event.target.value })} required /></label>
        <label><span>گذرواژه (حداقل ۸ نویسه)</span><input type="password" dir="ltr" value={userForm.password} onChange={(event) => setUserForm({ ...userForm, password: event.target.value })} minLength={8} required /></label>
        <label><span>نقش</span><select value={userForm.role} onChange={(event) => setUserForm({ ...userForm, role: event.target.value })}><option value="org_admin">مدیر سازمان</option><option value="operator">اپراتور</option><option value="viewer">بیننده</option></select></label>
        <PanelAccessEditor role={userForm.role} value={userForm.panel_permissions} disabled={userDialogBusy}
          onChange={panel_permissions => setUserForm({ ...userForm, panel_permissions })} />
        {userForm.role === "operator" ? <>
          <label><span>شماره موبایل اپراتور</span><input dir="ltr" inputMode="tel" value={userForm.mobile_number} onChange={(event) => setUserForm({ ...userForm, mobile_number: event.target.value })} /></label>
          <OperatorExtensionInput value={userForm.extension} disabled={userDialogBusy}
            onChange={extension => setUserForm({ ...userForm, extension })} />
          <p>برای اپراتور حداقل یکی از شماره موبایل یا شماره داخلی لازم است. اپراتور فقط تماس‌هایی را می‌بیند که خودش یک سمت آن باشد.</p>
        </> : null}
      </FormDialog>
    </div>
  );
}
