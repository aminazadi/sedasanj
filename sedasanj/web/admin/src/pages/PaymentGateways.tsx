import { useEffect, useState } from "react";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";
import zarinpalLogo from "../assets/payments/zarinpal.svg";
import zibalLogo from "../assets/payments/zibal.svg";
import samanLogo from "../assets/payments/saman.svg";
import behpardakhtLogo from "../assets/payments/behpardakht.svg";

interface Field { name: string; label: string; configured: boolean; hint: string }
interface Gateway {
  code: string; name: string; description: string; enabled: boolean; sandbox: boolean;
  supports_sandbox: boolean; configured: boolean; usable: boolean; min_toman: number;
  max_toman: number | null; supports_reverse: boolean; fields: Field[]; callback_url: string;
}
interface TestResult { ok: boolean; mode?: string; latency_ms?: number; code?: string; message?: string }

const LOGOS: Record<string, string> = { zarinpal: zarinpalLogo, zibal: zibalLogo, saman: samanLogo, behpardakht: behpardakhtLogo };
const SETUP_HINTS: Record<string, string> = {
  zarinpal: "در پنل زرین‌پال، IP سرور و دامنه‌ی callback را ثبت کنید (خطای ‎-۱۰ یعنی IP ثبت نشده، ‎-۱۴ یعنی دامنه نامطابق).",
  zibal: "Merchant ID را از پنل زیبال بگیرید. حالت آزمایشی از merchant مخصوص zibal استفاده می‌کند و نیازی به ورود مقدار نیست.",
  saman: "IP سرور و آدرس callback باید در پنل پذیرندگان سپ ثبت شده باشد؛ فقط پرداخت مبتنی بر توکن پشتیبانی می‌شود.",
  behpardakht: "ترمینال، نام کاربری و رمز را از بانک ملت بگیرید و IP سرور و دامنه‌ی callback را نزد بانک ثبت کنید (خطای ۴۲۱ یعنی IP ثبت نشده).",
};

function GatewayCard({ gateway, onSaved }: { gateway: Gateway; onSaved: (value: Gateway) => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);

  async function save(patch: { enabled?: boolean; sandbox?: boolean }) {
    setBusy(true); setError(null); setNotice(null);
    try {
      const credentials = Object.fromEntries(Object.entries(values).filter(([, value]) => value.trim()));
      const saved = await request<Gateway>(`/v1/admin/commerce/gateways/${gateway.code}`, { method: "PATCH", body: { ...patch, credentials } });
      setValues({}); setNotice("ذخیره شد."); onSaved(saved);
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  async function runTest() {
    setBusy(true); setError(null); setTest(null);
    try { setTest(await request<TestResult>(`/v1/admin/commerce/gateways/${gateway.code}/test`, { method: "POST" })); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  return (
    <section className="card space-y-4" aria-label={gateway.name}>
      <header className="flex flex-wrap items-center gap-3">
        <img src={LOGOS[gateway.code]} alt="" width={48} height={48} className="rounded-xl" />
        <div className="min-w-0 flex-1">
          <h2 className="font-bold">{gateway.name}</h2>
          <p className="text-xs text-slate-500">{gateway.description}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ${gateway.usable ? "bg-emerald-50 text-emerald-700" : gateway.configured ? "bg-amber-50 text-amber-700" : "bg-slate-100 text-slate-500"}`}>
          {gateway.usable ? "فعال و نمایش داده می‌شود" : gateway.configured ? "پیکربندی شده، غیرفعال" : "پیکربندی نشده"}
        </span>
      </header>
      <ErrorBox message={error} />
      {notice ? <div className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-700">{notice}</div> : null}
      <p className="text-xs leading-6 text-slate-500">{SETUP_HINTS[gateway.code]}</p>
      <div className="grid gap-3 md:grid-cols-2">
        {gateway.fields.map((field) => (
          <label key={field.name}>
            <span className="label">{field.label}</span>
            <input
              className="input" dir="ltr" autoComplete="off"
              type={field.name === "password" || field.name === "merchant_id" ? "password" : "text"}
              value={values[field.name] ?? ""}
              onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
              placeholder={field.configured ? `مقدار فعلی: ${field.hint} (برای تغییر، مقدار جدید بنویسید)` : "وارد نشده"}
            />
          </label>
        ))}
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <ToggleSwitch checked={gateway.enabled} disabled={busy} onChange={(checked) => void save({ enabled: checked })} label="نمایش به عنوان روش پرداخت" />
        {gateway.supports_sandbox ? <ToggleSwitch checked={gateway.sandbox} disabled={busy} onChange={(checked) => void save({ sandbox: checked })} label="حالت آزمایشی (sandbox)" /> : null}
      </div>
      <dl className="grid gap-1 text-xs text-slate-500 md:grid-cols-2">
        <div>حداقل مبلغ: {fmt.toman(gateway.min_toman)}</div>
        <div>حداکثر مبلغ: {gateway.max_toman ? fmt.toman(gateway.max_toman) : "بدون سقف"}</div>
        <div>برگشت خودکار از پنل: {gateway.supports_reverse ? "پشتیبانی می‌شود" : "ندارد (بازپرداخت دستی)"}</div>
        <div className="md:col-span-2">آدرس callback برای ثبت نزد بانک: <bdi dir="ltr" className="select-all font-mono">{gateway.callback_url}</bdi></div>
      </dl>
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn" disabled={busy || Object.values(values).every((value) => !value.trim())} onClick={() => void save({})}>ذخیره اطلاعات</button>
        <button className="btn-ghost" disabled={busy || !gateway.configured} onClick={() => void runTest()}>تست اتصال</button>
        {test ? <span className={`text-sm ${test.ok ? "text-emerald-700" : "text-rose-700"}`}>{test.ok ? `اتصال موفق (${test.mode === "sandbox" ? "آزمایشی" : "واقعی"}، ${fmt.int(test.latency_ms ?? 0)} میلی‌ثانیه)` : `ناموفق: ${test.message} — کد ${test.code}`}</span> : null}
      </div>
    </section>
  );
}

export default function PaymentGateways() {
  const [gateways, setGateways] = useState<Gateway[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { request<Gateway[]>("/v1/admin/commerce/gateways").then(setGateways).catch((reason) => setError(reason.message)); }, []);
  if (!gateways) return error ? <ErrorBox message={error} /> : <Loading />;
  return (
    <div className="max-w-4xl space-y-4">
      <div>
        <h1 className="text-2xl font-bold">درگاه‌های پرداخت</h1>
        <p className="mt-1 text-sm text-slate-500">فقط درگاه‌های فعال و کامل‌شده در صفحه‌ی پرداخت مشتریان نمایش داده می‌شوند. اطلاعات حساس رمزنگاری ذخیره می‌شود و دوباره نمایش داده نمی‌شود.</p>
      </div>
      <ErrorBox message={error} />
      {gateways.map((gateway) => (
        <GatewayCard key={gateway.code} gateway={gateway} onSaved={(saved) => setGateways(gateways.map((item) => (item.code === saved.code ? saved : item)))} />
      ))}
    </div>
  );
}
