import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "./Widgets";

interface DemoSettings {
  enabled: boolean; smsir_api_key_configured: boolean; smsir_api_key_hint: string;
  smsir_base_url: string; smsir_template_id: number; smsir_code_parameter: string;
  otp_ttl_seconds: number; otp_resend_seconds: number; otp_max_attempts: number;
  session_ttl_minutes: number; max_duration_seconds: number;
  max_calls_per_mobile: number; max_total_minutes: number;
  prompt_configured: boolean; prompt_url: string | null;
}
const numericFields: Array<{ key: keyof DemoSettings; label: string; min: number; max: number }> = [
  { key: "otp_ttl_seconds", label: "اعتبار کد تأیید (ثانیه)", min: 60, max: 600 },
  { key: "otp_resend_seconds", label: "فاصله ارسال دوباره (ثانیه)", min: 30, max: 300 },
  { key: "otp_max_attempts", label: "تعداد تلاش مجاز برای کد", min: 1, max: 10 },
  { key: "session_ttl_minutes", label: "اعتبار لینک QR (دقیقه)", min: 5, max: 60 },
  { key: "max_duration_seconds", label: "حداکثر مدت هر ضبط (ثانیه)", min: 10, max: 600 },
  { key: "max_calls_per_mobile", label: "سقف تعداد تست هر موبایل (صفر: فقط سقف دقیقه)", min: 0, max: 100 },
  { key: "max_total_minutes", label: "سقف مجموع دقیقه هر موبایل (صفر: اعتبار اولیه پلن دمو)", min: 0, max: 1000 },
];

export default function QuickDemoSettings() {
  const [settings, setSettings] = useState<DemoSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [testMobile, setTestMobile] = useState("");
  const [version, setVersion] = useState(Date.now());
  useEffect(() => { request<DemoSettings>("/v1/admin/quick-demo/settings").then(setSettings).catch((reason) => setError(reason.message)); }, []);
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!settings || busy) return;
    setBusy(true); setError(null); setNotice("");
    try {
      const { smsir_api_key_configured, smsir_api_key_hint, prompt_configured, prompt_url, ...values } = settings;
      void smsir_api_key_configured; void smsir_api_key_hint; void prompt_configured; void prompt_url;
      const result = await request<DemoSettings>("/v1/admin/quick-demo/settings", { method: "PATCH",
        body: { ...values, smsir_template_id: values.smsir_template_id || undefined, smsir_api_key: apiKey || undefined } });
      setSettings(result); setApiKey(""); setNotice("تنظیمات ذخیره شد.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  async function upload() {
    if (!file || busy) return;
    setBusy(true); setError(null); setNotice("");
    try {
      const body = new FormData(); body.append("file", file);
      const result = await request<DemoSettings>("/v1/admin/quick-demo/prompt", { method: "POST", body });
      setSettings((current) => current ? { ...current, prompt_configured: result.prompt_configured, prompt_url: result.prompt_url } : result);
      setFile(null); setVersion(Date.now()); setNotice("صدای آغازین ذخیره شد.");
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  async function testSms() {
    setBusy(true); setError(null); setNotice("");
    try { await request("/v1/admin/quick-demo/sms-test", { method: "POST", retry: false, body: { mobile: testMobile } }); setNotice("پیامک تست از قالب ذخیره‌شده ارسال شد."); }
    catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  if (!settings) return error ? <ErrorBox message={error}/> : <Loading/>;
  return <section className="card space-y-6" id="settings-panel-quick-demo" role="tabpanel" aria-labelledby="settings-tab-quick-demo">
    <ErrorBox message={error}/>{notice && <p className="text-sm text-emerald-700" role="status">{notice}</p>}
    <form onSubmit={save} className="space-y-5">
      <h2 className="text-lg font-bold">تست سریع و ورود پیامکی</h2>
      <label className="flex items-center gap-2"><input type="checkbox" checked={settings.enabled} onChange={(e) => setSettings({ ...settings, enabled: e.target.checked })}/>فعال‌بودن تست سریع و ساخت خودکار دمو</label>
      <div className="grid gap-4 md:grid-cols-2">
        <label><span className="label">کلید API سرویس SMS.ir {settings.smsir_api_key_configured ? `(${settings.smsir_api_key_hint})` : "(تنظیم نشده)"}</span><input className="input" type="password" dir="ltr" autoComplete="new-password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="برای حفظ کلید فعلی خالی بگذارید"/></label>
        <label><span className="label">آدرس سرویس</span><input className="input" type="url" dir="ltr" required value={settings.smsir_base_url} onChange={(e) => setSettings({ ...settings, smsir_base_url: e.target.value })}/></label>
        <label><span className="label">شناسه قالب خدماتی ارسال سریع</span><input className="input" type="number" min={1} value={settings.smsir_template_id || ""} onChange={(e) => setSettings({ ...settings, smsir_template_id: Number(e.target.value) })}/></label>
        <label><span className="label">نام پارامتر کد در قالب</span><input className="input" dir="ltr" required pattern="[A-Za-z][A-Za-z0-9_]{0,49}" value={settings.smsir_code_parameter} onChange={(e) => setSettings({ ...settings, smsir_code_parameter: e.target.value })}/></label>
        {numericFields.map(({ key, label, min, max }) => <label key={key}><span className="label">{label}</span><input className="input" type="number" required min={min} max={max} value={Number(settings[key])} onChange={(e) => setSettings({ ...settings, [key]: Number(e.target.value) })}/></label>)}
      </div>
      <p className="text-xs leading-6 text-slate-500">قالب باید در پنل SMS.ir تأیید شده باشد. نام پارامتر دقیقاً با قالب مطابقت داشته باشد. سقف تست هر موبایل در تمام سازمان‌ها مشترک است؛ لینک‌های فعال هم تا زمان انقضا ظرفیت رزرو می‌کنند.</p>
      <button className="btn" disabled={busy}>{busy ? "در حال انجام…" : "ذخیره تنظیمات تست سریع"}</button>
    </form>
    <div className="space-y-3 border-t border-slate-200 pt-5"><h3 className="font-bold">آزمایش ارسال پیامک</h3><div className="flex flex-wrap gap-3"><input className="input max-w-xs" type="tel" dir="ltr" placeholder="09121234567" value={testMobile} onChange={(e) => setTestMobile(fmt.latinDigits(e.target.value))}/><button className="btn" disabled={busy || !testMobile} onClick={() => void testSms()}>ارسال پیامک تست</button></div><p className="text-xs text-slate-500">آزمایش با تنظیمات ذخیره‌شده انجام می‌شود.</p></div>
    <div className="space-y-3 border-t border-slate-200 pt-5"><h3 className="font-bold">صدای آغازین مکالمه</h3><p className="text-sm leading-7 text-slate-500">صدایی بارگذاری کنید که از کاربر بخواهد پس از بوق صحبت کند. بوق به‌صورت خودکار بعد از این فایل پخش می‌شود. حداکثر ۲ دقیقه و ۲۰ مگابایت.</p>
      {settings.prompt_url && <audio key={version} controls src={`${settings.prompt_url}?v=${version}`} className="w-full"/>}
      <input type="file" accept="audio/*" onChange={(e) => setFile(e.target.files?.[0] || null)}/><button className="btn" disabled={busy || !file} onClick={() => void upload()}>بارگذاری صدای آغازین</button>
      {!settings.prompt_configured && <p className="text-sm text-amber-700">برای شروع ضبط کاربران، صدای آغازین را بارگذاری کنید.</p>}
    </div>
  </section>;
}
