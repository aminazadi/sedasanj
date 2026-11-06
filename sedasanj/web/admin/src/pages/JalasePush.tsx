import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import { useSensitiveAction } from "../components/SensitiveActionDialog";
import type { Page, Tenant, TenantUser } from "../types";
import "./JalasePush.css";

const base = "/v1/admin/jalase-negar/push";
const tabs = { compose: "ارسال", history: "تاریخچه", devices: "دستگاه‌ها", settings: "تنظیمات" };
const audiences = { all: "همه نصب‌های فعال", organization: "سازمان", user: "کاربر", devices: "دستگاه‌های انتخابی" };
const destinations = { home: "خانه", guide: "راهنما", people: "افراد", settings: "تنظیمات", models: "مدل‌ها" };
const channels = { "": "همه کانال‌ها", direct: "مستقیم", bazaar: "بازار", myket: "مایکت" };
const statuses = { "": "همه وضعیت‌ها", scheduled: "در انتظار شروع", cancelled: "لغوشده" };
const outcomes = { queued: "در صف", sending: "در حال ارسال", accepted: "پذیرفته‌شده توسط Firebase", failed: "ناموفق", cancelled: "لغوشده", unknown: "نامشخص" };
const errorText = (error: unknown) => error instanceof ApiError
  ? error.message : "ارتباط با سامانه برقرار نشد. اتصال را بررسی و دوباره تلاش کنید.";
const post = <T,>(path: string, body?: unknown) => request<T>(base + path, { method: "POST", body });

type Device = { id: string; channel: string; version: string; label: string | null; seen_at: string };
type Campaign = {
  id: string; title: string; scheduled_at: string; started_at: string | null;
  cancelled_at: string | null; expires_at: string; audience: keyof typeof audiences;
  counts: Partial<Record<keyof typeof outcomes, number>>;
};
type Listing<T> = { items: T[]; more: boolean };
type Config = { project: string; enabled: boolean; configured: boolean };
type Query = ReturnType<typeof useQuery>;

function useQuery() {
  const [params, setParams] = useSearchParams();
  function change(values: Record<string, string>) {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries(values)) {
        if (value) next.set(key, value);
        else next.delete(key);
      }
      return next;
    });
  }
  return { params, change };
}

function useLoad<T>(path: string | null, refresh = 0) {
  const [result, setResult] = useState<{ path: string; data?: T; error?: string }>();
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    void request<T>(path, { signal: controller.signal }).then(
      data => { if (!controller.signal.aborted) setResult({ path, data }); },
      error => { if (!controller.signal.aborted) setResult({ path, error: errorText(error) }); },
    );
    return () => controller.abort();
  }, [path, refresh]);
  return path === result?.path ? result : undefined;
}

function Field({ title, children }: { title: string; children: ReactNode }) {
  return <label className="push-field"><span>{title}</span>{children}</label>;
}

function Options({ values }: { values: Record<string, string> }) {
  return <>{Object.entries(values).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</>;
}

function Check({ children, value, onChange }: { children: ReactNode; value: boolean; onChange: (checked: boolean) => void }) {
  return <label className="push-check"><input type="checkbox" checked={value} onChange={event => onChange(event.target.checked)} />{children}</label>;
}

function ChannelVersion({ query, prefix }: { query: Query; prefix: string }) {
  const channel = prefix + "Channel";
  const version = prefix + "Version";
  return <div className="push-fields">
    <Field title="کانال انتشار"><select value={query.params.get(channel) ?? ""} onChange={event => query.change({ [channel]: event.target.value, [prefix === "send" ? "sendOffset" : "deviceOffset"]: "" })}><Options values={channels} /></select></Field>
    <Field title="نسخه اپ"><input dir="ltr" maxLength={64} placeholder="1.2.0" value={query.params.get(version) ?? ""} onChange={event => query.change({ [version]: event.target.value, [prefix === "send" ? "sendOffset" : "deviceOffset"]: "" })} /></Field>
  </div>;
}

function Pager({ offset, more, onChange }: { offset: number; more: boolean; onChange: (offset: number) => void }) {
  return <div className="push-actions">
    <button type="button" className="btn-ghost" disabled={!offset} onClick={() => onChange(Math.max(0, offset - 50))}>قبلی</button>
    <button type="button" className="btn-ghost" disabled={!more} onClick={() => onChange(offset + 50)}>بعدی</button>
  </div>;
}

function deviceName(device: Device) {
  return `${device.label || "نصب جلسه‌نگار"} · ${device.channel} · ${device.version} · ${device.id.slice(0, 8)}`;
}

function queryString(values: Record<string, string | number>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value) query.set(key, String(value));
  return query.toString();
}

function Compose({ query }: { query: Query }) {
  const { params, change } = query;
  const rawAudience = params.get("audience") ?? "all";
  const audience = Object.hasOwn(audiences, rawAudience) ? rawAudience : "all";
  const channel = params.get("sendChannel") ?? "";
  const version = params.get("sendVersion") ?? "";
  const organization = params.get("organization") ?? "";
  const user = params.get("user") ?? "";
  const orgOffset = Math.max(0, Number(params.get("orgOffset")) || 0);
  const setOrgOffset = (value: number) => change({ orgOffset: String(value) });
  const userOffset = Math.max(0, Number(params.get("userOffset")) || 0);
  const setUserOffset = (value: number) => change({ userOffset: String(value) });
  const deviceOffset = Math.max(0, Number(params.get("sendOffset")) || 0);
  const setDeviceOffset = (value: number) => change({ sendOffset: String(value) });
  const [selected, setSelected] = useState<string[]>([]);
  const [testDevice, setTestDevice] = useState("");
  const [kind, setKind] = useState("notification");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [image, setImage] = useState("");
  const [destination, setDestination] = useState("home");
  const [data, setData] = useState("{}");
  const [sound, setSound] = useState(true);
  const [replace, setReplace] = useState(false);
  const [priority, setPriority] = useState("normal");
  const [ttl, setTtl] = useState(3600);
  const [schedule, setSchedule] = useState("");
  const [preview, setPreview] = useState<{ signature: string; count: number }>();
  const [confirm, setConfirm] = useState(false);
  const [askProof, proofDialog] = useSensitiveAction();
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ signature: string; id: string }>();
  const orgs = useLoad<Page<Tenant>>(audience === "organization" || audience === "user"
    ? `/v1/admin/tenants?offset=${orgOffset}&limit=50` : null);
  const users = useLoad<Page<TenantUser>>(audience === "user" && organization
    ? `/v1/admin/tenants/${encodeURIComponent(organization)}/users?offset=${userOffset}&limit=50` : null);
  const devices = useLoad<Listing<Device>>(`${base}/devices?${queryString({ offset: deviceOffset, channel, version })}`);
  const signature = JSON.stringify([audience, channel, version, organization, user, selected,
    kind, title, body, image, destination, data, sound, replace, priority, ttl, schedule]);
  const currentPreview = preview?.signature === signature ? preview.count : undefined;
  const canSend = currentPreview !== undefined && (currentPreview > 0 || !!schedule);
  const silent = kind === "data";

  function buildMessage() {
    let custom: unknown = {};
    if (kind !== "notification") {
      try { custom = JSON.parse(data); }
      catch { throw new Error("دادهٔ سفارشی باید یک شیء JSON معتبر باشد."); }
      if (!custom || Array.isArray(custom) || typeof custom !== "object") throw new Error("دادهٔ سفارشی باید یک شیء JSON باشد.");
    }
    if (!silent && (!title.trim() || !body.trim())) throw new Error("عنوان و متن اعلان را وارد کنید.");
    if (!silent && image && !/^https:\/\//i.test(image)) throw new Error("نشانی تصویر باید با HTTPS شروع شود.");
    return {
      kind, data: custom, title: silent ? "" : title, body: silent ? "" : body,
      image: silent ? null : image || null, destination: silent ? "home" : destination,
      sound: !silent && sound, replace: !silent && replace, priority: silent ? "normal" : priority, ttl,
    };
  }

  async function action(mode: "preview" | "test" | "send") {
    if (busy) return;
    setError("");
    setFeedback("");
    setBusy(true);
    try {
      const message = buildMessage();
      const payload = mode === "test"
        ? { installation_id: testDevice, message }
        : {
            audience: { kind: audience, channel: channel || null, version: version || null,
              organization_id: audience === "organization" ? organization || null : null,
              user_id: audience === "user" ? user || null : null,
              device_ids: audience === "devices" ? selected : [] },
            message,
            scheduled_at: schedule ? new Date(schedule + "+03:30").toISOString() : null,
          };
      if (mode === "preview") {
        const result = await post<{ count: number }>("/preview", payload);
        setPreview({ signature, count: result.count });
        setConfirm(false);
        return;
      }
      const broadcast = mode === "send" && audience === "all";
      const proof = broadcast ? await askProof("برای تأیید ارسال سراسری، هویت خود را تأیید کنید.") : null;
      if (broadcast && !proof) return;
      const operation = JSON.stringify([mode, payload]);
      if (pending.current?.signature !== operation) pending.current = { signature: operation, id: crypto.randomUUID() };
      await post(mode === "test" ? "/test" : "/campaigns", {
        ...payload, id: pending.current.id, ...(mode === "send" ? { confirmed_all: confirm, proof } : {}),
      });
      pending.current = undefined;
      setPreview(undefined);
      setConfirm(false);
      setFeedback("ارسال در صف ثبت شد. نتیجه را در تاریخچه ببینید.");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : errorText(failure));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (canSend && (audience !== "all" || confirm)) void action("send");
  }

  return <div className="push-compose">
    <form className="push-card" onSubmit={submit}>
      <h2>مخاطبان</h2>
      <Field title="گروه مخاطب"><select value={audience} onChange={event => change({ audience: event.target.value, organization: "", user: "" })}><Options values={audiences} /></select></Field>
      {(audience === "organization" || audience === "user") && <>
        <Field title="سازمان"><select value={organization} onChange={event => { change({ organization: event.target.value, user: "", userOffset: "" }); }}>
          <option value="">انتخاب سازمان</option>
          {organization && !orgs?.data?.items.some(item => item.id === organization) && <option value={organization}>{organization}</option>}
          {orgs?.data?.items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></Field>
        <Pager offset={orgOffset} more={(orgs?.data?.items.length ?? 0) === 50} onChange={setOrgOffset} />
        {orgs?.error && <p role="alert">{orgs.error}</p>}
      </>}
      {audience === "user" && organization && <>
        <Field title="کاربر"><select value={user} onChange={event => change({ user: event.target.value })}>
          <option value="">انتخاب کاربر</option>
          {user && !users?.data?.items.some(item => item.id === user) && <option value={user}>{user}</option>}
          {users?.data?.items.map(item => <option key={item.id} value={item.id}>{item.email}</option>)}
        </select></Field>
        <Pager offset={userOffset} more={(users?.data?.items.length ?? 0) === 50} onChange={setUserOffset} />
        {users?.error && <p role="alert">{users.error}</p>}
      </>}
      <ChannelVersion query={query} prefix="send" />
      {audience === "devices" && <fieldset className="push-devices">
        <legend>دستگاه‌ها · {fmt.int(selected.length)} انتخاب</legend>
        {devices?.data?.items.map(device => <Check key={device.id} value={selected.includes(device.id)}
          onChange={checked => setSelected(previous => checked ? [...previous, device.id].slice(0, 200) : previous.filter(id => id !== device.id))}>{deviceName(device)}</Check>)}
        <button type="button" className="btn-ghost" onClick={() => setSelected([])}>پاک‌کردن انتخاب</button>
      </fieldset>}
      <h2>پیام</h2>
      <Field title="نوع پیام"><select value={kind} onChange={event => setKind(event.target.value)}><Options values={{ notification: "اعلان", combined: "اعلان همراه داده", data: "پیام داده‌ای بی‌صدا" }} /></select></Field>
      {!silent && <>
        <Field title="عنوان"><input maxLength={180} value={title} onChange={event => setTitle(event.target.value)} /></Field>
        <Field title="متن"><textarea rows={4} maxLength={2000} value={body} onChange={event => setBody(event.target.value)} /></Field>
        <Field title="تصویر HTTPS"><input dir="ltr" type="url" value={image} onChange={event => setImage(event.target.value)} /></Field>
        <Field title="مقصد لمس اعلان"><select value={destination} onChange={event => setDestination(event.target.value)}><Options values={destinations} /></select></Field>
        <div className="push-actions">
          <Check value={sound} onChange={setSound}>صدا</Check>
          <Check value={replace} onChange={setReplace}>جایگزینی اعلان قبلی</Check>
        </div>
        <Field title="اولویت"><select value={priority} onChange={event => setPriority(event.target.value)}><Options values={{ normal: "عادی", high: "بالا" }} /></select></Field>
      </>}
      {kind !== "notification" && <Field title="دادهٔ سفارشی JSON"><textarea dir="ltr" rows={5} value={data} onChange={event => setData(event.target.value)} /></Field>}
      <div className="push-fields">
        <Field title="اعتبار پیام به ثانیه"><input dir="ltr" type="number" required min={60} max={2419200} value={ttl || ""} onChange={event => setTtl(Number(event.target.value))} /></Field>
        <Field title="زمان ارسال به وقت تهران، خالی برای فوری"><input dir="ltr" type="datetime-local" value={schedule} onChange={event => setSchedule(event.target.value)} /></Field>
      </div>
      <div className="push-actions">
        <button type="button" className="btn-ghost" disabled={busy} onClick={() => void action("preview")}>شمارش مخاطبان</button>
        {currentPreview !== undefined && <strong>{fmt.int(currentPreview)} دستگاه</strong>}
      </div>
      {audience === "all" && canSend && <Check value={confirm} onChange={setConfirm}>ارسال سراسری برای مخاطبان انتخاب‌شده را تأیید می‌کنم</Check>}
      <button type="submit" className="btn-primary" disabled={busy || !canSend || (audience === "all" && !confirm)}>{schedule ? "ثبت ارسال زمان‌بندی‌شده" : "ارسال فوری"}</button>
      {error && <p role="alert">{error}</p>}
      {feedback && <p role="status">{feedback}</p>}
    </form>
    <aside className="push-card">
      <h2>پیش‌نمایش گوشی</h2>
      <div className="push-phone">
        {silent ? <div className="push-notification">پیام داده‌ای بی‌صدا روی صفحهٔ اعلان نمایش ندارد.</div>
          : <div className="push-notification"><small>جلسه‌نگار</small><strong>{title || "عنوان اعلان"}</strong><p>{body || "متن اعلان اینجا نمایش داده می‌شود."}</p>
            {/^https:\/\//i.test(image) && <img src={image} alt="تصویر اعلان" referrerPolicy="no-referrer" />}
          </div>}
      </div>
      <h2>ارسال آزمایشی</h2>
      <Field title="دستگاه آزمایش"><select value={testDevice} onChange={event => setTestDevice(event.target.value)}>
        <option value="">انتخاب دستگاه</option>
        {testDevice && !devices?.data?.items.some(item => item.id === testDevice) && <option value={testDevice}>{testDevice}</option>}
        {devices?.data?.items.map(device => <option key={device.id} value={device.id}>{deviceName(device)}</option>)}
      </select></Field>
      <Pager offset={deviceOffset} more={!!devices?.data?.more} onChange={setDeviceOffset} />
      {devices?.error && <p role="alert">{devices.error}</p>}
      <button type="button" className="btn-ghost" disabled={!testDevice || busy} onClick={() => void action("test")}>ارسال به دستگاه آزمایش</button>
    </aside>
    {proofDialog}
  </div>;
}

function Devices({ query }: { query: Query }) {
  const offset = Math.max(0, Number(query.params.get("deviceOffset")) || 0);
  const result = useLoad<Listing<Device>>(`${base}/devices?${queryString({
    offset, channel: query.params.get("deviceChannel") ?? "", version: query.params.get("deviceVersion") ?? "",
  })}`);
  return <section className="push-card">
    <ChannelVersion query={query} prefix="device" />
    {result?.error && <p role="alert">{result.error}</p>}
    {result?.data?.items.length === 0 && <p>دستگاه فعالی برای این فیلتر پیدا نشد.</p>}
    {result?.data?.items.map(device => <div key={device.id} className="push-row">
      <div><strong>{deviceName(device)}</strong><div dir="ltr" className="push-id">{device.id}</div></div>
      <time dateTime={device.seen_at}>{fmt.dateTime(device.seen_at)}</time>
    </div>)}
    <Pager offset={offset} more={!!result?.data?.more} onChange={value => query.change({ deviceOffset: String(value) })} />
  </section>;
}

function History({ query }: { query: Query }) {
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const offset = Math.max(0, Number(query.params.get("historyOffset")) || 0);
  const status = query.params.get("status") ?? "";
  const result = useLoad<Listing<Campaign>>(`${base}/campaigns?${queryString({ offset, status })}`, refresh);
  async function cancel(id: string) {
    if (!window.confirm("ارسال به گیرندگان باقی‌مانده متوقف شود؟")) return;
    setBusy(true);
    setError("");
    try { await post(`/campaigns/${id}/cancel`); setRefresh(value => value + 1); }
    catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); }
  }
  return <section className="push-card">
    <div className="push-actions">
      <Field title="وضعیت"><select aria-label="وضعیت" value={status} onChange={event => query.change({ status: event.target.value, historyOffset: "" })}><Options values={statuses} /></select></Field>
      <button className="btn-ghost" onClick={() => setRefresh(value => value + 1)}>به‌روزرسانی</button>
    </div>
    {(error || result?.error) && <p role="alert">{error || result?.error}</p>}
    {result?.data?.items.length === 0 && <p>ارسالی برای این فیلتر ثبت نشده است.</p>}
    {result?.data?.items.map(row => <article key={row.id} className="push-row">
      <div>
        <h2>{row.title || "پیام داده‌ای"}</h2>
        <p>{audiences[row.audience]} · {fmt.dateTime(row.scheduled_at)}{row.cancelled_at ? " · لغوشده" : ""}</p>
        <dl className="push-outcomes">
          <div><dt>انتخاب‌شده</dt><dd>{fmt.int(Object.values(row.counts).reduce((a, b) => a + b, 0))}</dd></div>
          {Object.entries(outcomes).map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{fmt.int(row.counts[key as keyof typeof outcomes] ?? 0)}</dd></div>)}
        </dl>
      </div>
      {!row.cancelled_at && new Date(row.expires_at).getTime() > Date.now() &&
        (!row.started_at || !!row.counts.queued || !!row.counts.sending) &&
        <button className="btn-ghost" disabled={busy} onClick={() => void cancel(row.id)}>لغو ارسال</button>}
    </article>)}
    <Pager offset={offset} more={!!result?.data?.more} onChange={value => query.change({ historyOffset: String(value) })} />
  </section>;
}

function Settings({ initial }: { initial: Config }) {
  const [config, setConfig] = useState(initial);
  const [askProof, proofDialog] = useSensitiveAction();
  const [credentials, setCredentials] = useState("");
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  async function run(check: boolean) {
    setBusy(true);
    setError("");
    setFeedback("");
    try {
      if (check) {
        await post("/settings/check");
        setFeedback("اتصال و مجوز ارسال Firebase تأیید شد.");
      } else {
        const proof = await askProof("برای تغییر تنظیمات پوش، هویت خود را تأیید کنید.");
        if (!proof) return;
        const saved = await request<Config>(base + "/settings", {
          method: "PUT", body: { enabled: config.enabled, project: config.project, credentials: credentials || null, ...proof },
        });
        setConfig(saved);
        setCredentials("");
        setFeedback("تنظیمات ذخیره شد.");
      }
    } catch (failure) { setError(errorText(failure)); }
    finally { setBusy(false); }
  }
  return <><form className="push-card push-settings" onSubmit={event => { event.preventDefault(); void run(false); }}>
    <Field title="شناسهٔ پروژهٔ Firebase"><input dir="ltr" required value={config.project} onChange={event => setConfig({ ...config, project: event.target.value })} /></Field>
    <Field title={config.configured ? "جایگزینی اعتبارنامهٔ ذخیره‌شده (JSON)" : "اعتبارنامهٔ حساب سرویس Firebase (JSON)"}>
      <textarea rows={4} dir="ltr" autoComplete="off" spellCheck={false} className="push-secret"
        value={credentials} onChange={event => setCredentials(event.target.value)} />
    </Field>
    <Check value={config.enabled} onChange={enabled => setConfig({ ...config, enabled })}>فعال‌سازی ارسال پوش</Check>
    <div className="push-actions">
      <button type="submit" className="btn-primary" disabled={busy}>ذخیره</button>
      <button type="button" className="btn-ghost" disabled={busy || !config.configured} onClick={() => void run(true)}>آزمون تنظیمات ذخیره‌شده</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {feedback && <p role="status">{feedback}</p>}
  </form>{proofDialog}</>;
}

export default function JalasePush() {
  const query = useQuery();
  const rawTab = query.params.get("tab") ?? "compose";
  const tab = Object.hasOwn(tabs, rawTab) ? rawTab : "compose";
  const config = useLoad<Config>(tab === "settings" ? base + "/settings" : null);
  return <div className="jalase-push" dir="rtl">
    <h1>پوش جلسه‌نگار</h1>
    <nav className="push-tabs" aria-label="بخش‌های پوش جلسه‌نگار">
      {Object.entries(tabs).map(([key, label]) => <button key={key} type="button"
        aria-current={key === tab ? "page" : undefined} onClick={() => query.change({ tab: key })}>{label}</button>)}
    </nav>
    {tab === "compose" && <Compose query={query} />}
    {tab === "devices" && <Devices query={query} />}
    {tab === "history" && <History query={query} />}
    {tab === "settings" && (config?.data ? <Settings initial={config.data} /> : config?.error
      ? <p role="alert">{config.error}</p> : <p role="status">در حال بارگذاری تنظیمات…</p>)}
  </div>;
}
