import { useEffect, useState } from "react";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import { Link } from "react-router-dom";
import { request } from "../api";
import { freePbxModuleConfig } from "../agentConfig";
import { ErrorBox, Pagination } from "../components/Widgets";
import type { Page } from "../types";

const DIALPLAN = `[from-internal]
exten => _X.,1,NoOp(CBI record \${UNIQUEID})
 same => n,MixMonitor(\${UNIQUEID}.wav,abr(\${UNIQUEID}-in.wav)t(\${UNIQUEID}-out.wav))
 same => n,Dial(PJSIP/\${EXTEN},,Ttr)
 same => n,Hangup()`;

const CONFIG = `# /etc/cbi-agent/cbi-agent.toml
[server]
base_url = "${window.location.origin}"
timeout_seconds = 60

[auth]
api_key = "sk_live_..."

[archive]
format = "gzip"
# For AES-256 ZIP only:
# password = "your-one-time-password"

[asterisk]
ami_host = "127.0.0.1"
ami_port = 5038
ami_user = "cbi"
ami_secret = "..."
monitor_dir = "/var/spool/asterisk/monitor"

[audio]
sample_rate = 8000
channels = 2
delete_after_upload = true

[retry]
max_attempts = 100
backoff_seconds = 30
retry_max_seconds = 3600
credit_retry_seconds = 3600

[spool]
dir = "/var/lib/cbi-agent/spool"`;

const FREEPBX_CONFIG = freePbxModuleConfig(
  window.location.origin,
  "00000000-0000-4000-8000-000000000000",
  "sk_live_example",
  "sk_live_example_REPLACE_WITH_REAL_SECRET",
  "gzip",
  "",
  "2026-01-01T00:00:00.000Z",
);

function Block({ title, code }: { title: string; code: string }) {
  return (
    <div className="card">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="font-bold">{title}</h2>
        <button className="btn-ghost text-xs" onClick={() => void navigator.clipboard.writeText(code)}>
          کپی
        </button>
      </div>
      <pre dir="ltr" className="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
        {code}
      </pre>
    </div>
  );
}

export default function Install() {
  const limit = 10;
  const [installationOffset, setInstallationOffset] = useState(0);
  const [installationTotal, setInstallationTotal] = useState(0);
  const [key, setKey] = useState("");
  const [result, setResult] = useState<{ tenant: string | null; balance_minutes: number; archive_format: string; archive_password_configured: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [installations, setInstallations] = useState<Array<{ id: string; kind: string; status: string; pbx_type: string; order_id: string | null }>>([]);
  const [installForm, setInstallForm] = useState({ kind: "initial", pbx_type: "Asterisk", pbx_version: "", extension_count: 1, connection_method: "API Agent", technical_contact: "", preferred_time: "", notes: "" });

  async function reloadInstallations() {
    const page = await request<Page<{ id: string; kind: string; status: string; pbx_type: string; order_id: string | null }>>(`/v1/installation-requests?limit=${limit}&offset=${installationOffset}`);
    setInstallations(page.items);
    setInstallationTotal(page.total);
  }

  useEffect(() => { void reloadInstallations(); }, [installationOffset]);

  async function createInstallation(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const result = await request<{ order_id: string | null }>("/v1/installation-requests", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: installForm });
      if (result.order_id) {
        const payment = await request<{ redirect_url: string }>(`/v1/orders/${result.order_id}/pay`, { method: "POST" });
        window.location.assign(payment.redirect_url);
        return;
      }
      await reloadInstallations();
    } catch (reason) { setError((reason as Error).message); }
  }

  async function test(event: React.FormEvent) {
    event.preventDefault();
    setResult(null);
    setError(null);
    try {
      const response = await fetch("/v1/ingest/health", {
        headers: { Authorization: `Bearer ${key}` },
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.error?.message ?? `خطای ${response.status}`);
        return;
      }
      setResult(await response.json());
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <div className="card"><h1 className="mb-2 text-xl font-bold">درخواست نصب و استقرار</h1><p className="mb-4 text-sm text-slate-500">نصب اولیه عادی یک‌بار رایگان است؛ نصب مجدد ۳ میلیون و نصب اختصاصی ۲۰ میلیون تومان است.</p><form className="grid gap-3 md:grid-cols-2" onSubmit={createInstallation}><select className="input" value={installForm.kind} onChange={(event) => setInstallForm({ ...installForm, kind: event.target.value })}><option value="initial">نصب اولیه رایگان</option><option value="reinstall">نصب مجدد عادی</option><option value="dedicated">نصب اختصاصی</option></select><input className="input" required placeholder="نوع PBX" value={installForm.pbx_type} onChange={(event) => setInstallForm({ ...installForm, pbx_type: event.target.value })}/><input className="input" placeholder="نسخه PBX" value={installForm.pbx_version} onChange={(event) => setInstallForm({ ...installForm, pbx_version: event.target.value })}/><input className="input" type="number" min={1} required placeholder="تعداد داخلی" value={installForm.extension_count} onChange={(event) => setInstallForm({ ...installForm, extension_count: Number(event.target.value) })}/><input className="input" required placeholder="روش اتصال" value={installForm.connection_method} onChange={(event) => setInstallForm({ ...installForm, connection_method: event.target.value })}/><input className="input" required placeholder="نام و تماس مسئول فنی" value={installForm.technical_contact} onChange={(event) => setInstallForm({ ...installForm, technical_contact: event.target.value })}/><JalaliDatePicker includeTime value={installForm.preferred_time} onChange={(value) => setInstallForm({ ...installForm, preferred_time: value })} placeholder="زمان ترجیحی نصب"/><input className="input" placeholder="توضیحات غیرمحرمانه" value={installForm.notes} onChange={(event) => setInstallForm({ ...installForm, notes: event.target.value })}/><button className="btn md:col-span-2">ثبت درخواست</button></form>{installations.length ? <div className="mt-5 overflow-x-auto"><table className="table"><thead><tr><th>نوع</th><th>PBX</th><th>وضعیت</th></tr></thead><tbody>{installations.map((item) => <tr key={item.id}><td>{item.kind}</td><td>{item.pbx_type}</td><td>{item.status}</td></tr>)}</tbody></table><Pagination page={Math.floor(installationOffset/limit)+1} hasPrevious={installationOffset>0} hasNext={installationOffset+limit<installationTotal} total={installationTotal} onPrevious={()=>setInstallationOffset(Math.max(0,installationOffset-limit))} onNext={()=>setInstallationOffset(installationOffset+limit)}/></div> : null}</div>
      <div className="card bg-gradient-to-l from-brand-50 to-white">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="mb-3 text-xl font-bold">راه‌اندازی امن روی سرور Asterisk</h1>
            <p className="text-sm leading-6 text-slate-600">
              از ضبط تماس تا ارسال فشرده، صف retry و شروع پردازش را مرحله‌به‌مرحله تنظیم کنید.
            </p>
          </div>
          <Link className="btn" to="/api-docs">مشاهده مستندات کامل API</Link>
        </div>
        <ol className="mt-5 list-decimal space-y-3 ps-6 text-right text-sm leading-7 text-slate-700">
          <li>ffmpeg و پایتون ۳٫۱۲ را روی سرور تلفنی نصب کنید.</li>
          <li>یک API key با فرمت GZIP یا ZIP بسازید و خروجی مخصوص روش اتصال خود را دانلود کنید.</li>
          <li>برای FreePBX، ماژول Seda Sanj را نصب و JSON را در تب Import Configuration بارگذاری و تأیید کنید.</li>
          <li>برای Python Agent، TOML را در /etc/cbi-agent قرار دهید و AMI read-only را تنظیم کنید.</li>
          <li>در FreePBX ضبط دوکاناله توسط ماژول مدیریت می‌شود؛ dialplan زیر فقط برای Python Agent است.</li>
          <li>پس از نصب، اعتبارسنجی تنظیمات و یک تماس آزمایشی ورودی و خروجی انجام دهید.</li>
        </ol>
        <div className="mt-3">
          <button
            className="btn-ghost"
            onClick={() =>
              void request<{ status: string }>("/v1/billing/balance").then(() => undefined)
            }
          >
            بارگذاری مجدد وضعیت حساب
          </button>
        </div>
      </div>

      <Block title="نمونه فایل قابل Import در FreePBX" code={FREEPBX_CONFIG} />
      <Block title="قطعه dialplan Python Agent (extensions.conf)" code={DIALPLAN} />
      <Block title="فایل تنظیمات Python Agent" code={CONFIG} />

      <div className="card overflow-x-auto">
        <h2 className="mb-3 font-bold">رفتار خطا و بازیابی</h2>
        <table className="table min-w-[620px]"><thead><tr><th>وضعیت</th><th>نمونه</th><th>رفتار agent</th></tr></thead><tbody><tr><td>کمبود اعتبار</td><td dir="ltr">402</td><td>blocked_credit؛ بدون مصرف attempt و ادامه خودکار پس از شارژ</td></tr><tr><td>موقت</td><td dir="ltr">429, 5xx, timeout</td><td>نگه‌داری در spool و retry با backoff</td></tr><tr><td>دائمی</td><td dir="ltr">401, 403, 413, 415, 422</td><td>انتقال metadata به dead-letter و نگه‌داری فایل برای بررسی</td></tr><tr><td>موفق یا تکراری</td><td dir="ltr">200, 201</td><td>پاک‌سازی یا انتقال به uploaded طبق تنظیمات</td></tr></tbody></table>
      </div>

      <div className="card">
        <h2 className="mb-2 font-bold">آزمون اتصال عامل</h2>
        <form className="flex flex-wrap gap-2" onSubmit={test}>
          <input
            className="input md:w-96"
            dir="ltr"
            placeholder="sk_live_..."
            value={key}
            onChange={(event) => setKey(event.target.value)}
            required
          />
          <button className="btn">آزمون /v1/ingest/health</button>
        </form>
        <ErrorBox message={error} />
        {result ? <div className="mt-3 grid gap-2 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 md:grid-cols-4"><div><span className="block text-xs text-emerald-700">سازمان</span>{result.tenant ?? "—"}</div><div><span className="block text-xs text-emerald-700">اعتبار</span>{result.balance_minutes} دقیقه</div><div><span className="block text-xs text-emerald-700">فرمت</span>{result.archive_format?.toUpperCase()}</div><div><span className="block text-xs text-emerald-700">رمز ZIP</span>{result.archive_password_configured ? "فعال" : "غیرفعال"}</div></div> : null}
      </div>
    </div>
  );
}
