import { useEffect, useState } from "react";
import { request } from "../api";
import { useAuth } from "../auth";
import { ErrorBox } from "./Widgets";

type Slots = { head: string; body: string };
type Settings = { public: Slots; customer: Slots };

export default function SiteScriptsSettings() {
  const { session } = useAuth();
  const [value, setValue] = useState<Settings | null>(null);
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (session?.role !== "super_admin") return;
    request<Settings>("/v1/admin/site-scripts").then(setValue).catch(() => setError("دریافت اسکریپت‌ها انجام نشد. صفحه را تازه کنید."));
  }, [session?.role]);
  if (session?.role !== "super_admin") return null;
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!value || busy) return;
    setBusy(true); setError(null); setNotice("");
    try {
      const saved = await request<Settings>("/v1/admin/site-scripts", { method: "PUT", body: { ...value, current_password: password, totp_code: totp || null } });
      setValue(saved); setPassword(""); setTotp("");
      setNotice("اسکریپت‌ها ذخیره شدند. صفحات مقصد را دوباره بارگذاری کنید.");
    } catch {
      setError("ذخیره انجام نشد. رمز عبور و کد دومرحله‌ای را بررسی کنید؛ هر فیلد باید حداکثر ۳۰ تگ script بسته‌شده و ۱۰۰٬۰۰۰ نویسه داشته باشد. نشانی src باید HTTPS یا مسیر داخلی باشد. سپس دوباره ذخیره کنید.");
    } finally { setBusy(false); }
  }
  return <section className="card space-y-4">
    <div><h2 className="text-lg font-bold">اسکریپت‌های صفحات</h2><p className="mt-2 text-sm leading-7 text-slate-500">کد ابزارهای آمار، پشتیبانی و سرویس‌های دیگر را برای صفحات عمومی و پنل مشتری جداگانه وارد کنید. این کدها به صفحه و اطلاعات قابل مشاهده مشتری دسترسی دارند؛ فقط کد سرویس مورد اعتماد را قرار دهید. این کدها در پنل ادمین اجرا نمی‌شوند.</p></div>
    <ErrorBox message={error} />
    {notice && <p role="status" className="text-sm text-emerald-700">{notice}</p>}
    {value && <form onSubmit={save} className="space-y-5"><fieldset disabled={busy} className="space-y-5">
      {([ ["public", "صفحات عمومی"], ["customer", "پنل مشتری"] ] as const).map(([scope, title]) => <div key={scope} className="space-y-3"><h3 className="font-bold">{title}</h3>{(["head", "body"] as const).map(slot => <label key={slot} className="block"><span className="label">{slot === "head" ? "داخل head" : "انتهای body"}</span><textarea className="input min-h-48 font-mono text-left" dir="ltr" spellCheck={false} maxLength={100000} value={value[scope][slot]} placeholder={'<script src="https://example.com/widget.js"></script>'} onChange={event => setValue({ ...value, [scope]: { ...value[scope], [slot]: event.target.value } })} /></label>)}</div>)}
      <p className="text-xs leading-6 text-slate-500">کد را همراه تگ script وارد کنید. برای حذف، فیلد را خالی و ذخیره کنید. اجرا پس از تشخیص وضعیت ورود انجام می‌شود و در جابه‌جایی بین صفحات همان بخش تکرار نمی‌شود. هنگام ورود یا خروج، صفحه برای جداسازی اسکریپت‌های دو بخش دوباره بارگذاری می‌شود. کدهای نیازمند اجرای هم‌زمان با تجزیه اولیه HTML یا document.write پشتیبانی نمی‌شوند.</p>
      <label className="block"><span className="label">رمز عبور مدیر کل</span><input required type="password" autoComplete="current-password" className="input" value={password} onChange={e => setPassword(e.target.value)} /></label>
      <label className="block"><span className="label">کد دومرحله‌ای (در صورت فعال بودن)</span><input className="input" inputMode="numeric" autoComplete="one-time-code" dir="ltr" value={totp} onChange={e => setTotp(e.target.value)} /></label>
      <button className="btn" disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیره اسکریپت‌ها"}</button>
    </fieldset></form>}
  </section>;
}
