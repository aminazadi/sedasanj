import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "./Widgets";

interface SiteContactSettingsValue { phone: string; trust_html: string }

export default function SiteContactSettings() {
  const [value, setValue] = useState<SiteContactSettingsValue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request<SiteContactSettingsValue>("/v1/admin/site-contact-settings")
      .then((settings) => setValue({ ...settings, phone: fmt.digits(settings.phone) }))
      .catch((reason) => setError(reason.message));
  }, []);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      const saved = await request<SiteContactSettingsValue>("/v1/admin/site-contact-settings", {
        method: "PATCH",
        body: { ...value, phone: fmt.latinDigits(value.phone) },
      });
      setValue({ ...saved, phone: fmt.digits(saved.phone) });
      setNotice("تنظیمات سایت ذخیره شد.");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!value) return error ? <ErrorBox message={error} /> : <Loading />;

  return <section id="settings-panel-site-contact" role="tabpanel" aria-labelledby="settings-tab-site-contact" className="card space-y-5">
    <div><h2 className="text-lg font-bold">تنظیمات سایت</h2><p className="mt-1 text-sm text-slate-500">شماره تماس فوتر و کد HTML نمادهای اعتماد صفحه اصلی را مدیریت کنید.</p></div>
    <ErrorBox message={error}/>
    {notice && <p className="text-sm text-emerald-700" role="status">{notice}</p>}
    <form className="space-y-5" onSubmit={save}>
      <label className="block"><span className="label">شماره تماس فوتر</span><input className="input" type="tel" inputMode="tel" dir="ltr" required minLength={10} maxLength={15} value={value.phone} onChange={(event) => setValue({ ...value, phone: fmt.digits(fmt.latinDigits(event.target.value).replace(/\D/g, "")) })}/></label>
      <label className="block"><span className="label">کد HTML نمادهای اعتماد</span><textarea className="input min-h-48 font-mono text-left" dir="ltr" spellCheck={false} maxLength={20000} value={value.trust_html} onChange={(event) => setValue({ ...value, trust_html: event.target.value })} placeholder="کد HTML نمادهای اعتماد را اینجا قرار دهید"/></label>
      <p className="text-xs leading-6 text-slate-500">محتوای نماد در صفحه اصلی داخل قاب ایزوله نمایش داده می‌شود و به بخش‌های دیگر سایت دسترسی ندارد.</p>
      <button className="btn" disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیره تنظیمات سایت"}</button>
    </form>
  </section>;
}
