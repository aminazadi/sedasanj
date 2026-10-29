import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { ErrorBox } from "./Widgets";
import twoFactorArt from "../assets/two-factor.svg";

const endpoint = "/v1/auth/totp";

export default function TwoFactorSettings() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [secret, setSecret] = useState("");
  const [uri, setUri] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    request<{ enabled: boolean }>(endpoint).then((value) => setEnabled(value.enabled)).catch((err) => setError(err.message));
  }, []);

  async function start() {
    setBusy(true); setError("");
    try {
      const result = await request<{ secret: string; uri: string }>(endpoint + "/setup", { method: "POST" });
      setSecret(result.secret); setUri(result.uri);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const result = await request<{ enabled: boolean }>(endpoint + (enabled ? "/disable" : "/enable"), {
        method: "POST", body: enabled ? { password, code } : { code },
      });
      setEnabled(result.enabled); setSecret(""); setUri(""); setCode(""); setPassword("");
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  const codeField = (id: string, label: string) => <div>
    <label className="label" htmlFor={id}>{label}</label>
    <input id={id} className="input" dir="ltr" inputMode="numeric" pattern="[0-9]{6}" autoComplete="one-time-code" value={fmt.digits(code)} onChange={(e) => setCode(fmt.latinDigits(e.target.value).replace(/\D/g, "").slice(0, 6))} required />
  </div>;
  const step = (index: number, title: string, children?: React.ReactNode) => <li className="flex gap-3">
    <span className="flex h-7 w-7 shrink-0 items-center justify-center bg-[#4B6E48] text-sm font-bold text-[#F2F0EF]" aria-hidden="true">{index}</span>
    <div className="min-w-0 flex-1 space-y-2"><p className="text-sm font-medium leading-7">{title}</p>{children}</div>
  </li>;

  return <section className="card">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="font-bold">ورود دومرحله‌ای با گوگل آتنتیکیتور</h2>
      {enabled === null ? <span className="badge badge-neutral">در حال بررسی…</span> : enabled ? <span className="badge badge-success">فعال</span> : <span className="badge badge-warning">غیرفعال</span>}
    </div>
    <ErrorBox message={error || null} />
    <div className="grid items-center gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0 space-y-5">
        <p className="text-sm leading-7 text-slate-500">بعد از گذرواژه، یک کد شش‌رقمی از برنامهٔ روی گوشی شما هم لازم است؛ حتی با لو رفتن گذرواژه، ورود غیرمجاز ممکن نیست.</p>

        {enabled === null ? null : enabled ? <form onSubmit={submit} className="space-y-3">
          <p className="text-sm font-medium">برای غیرفعال‌سازی، گذرواژه و کد فعلی را وارد کنید.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="totp-password">گذرواژه فعلی</label>
              <input id="totp-password" type="password" className="input" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {codeField("totp-code", "کد گوگل آتنتیکیتور")}
          </div>
          <button className="btn-danger" disabled={busy}>غیرفعال‌سازی</button>
        </form> : secret ? <ol className="space-y-5">
          {step(1, "برنامهٔ Google Authenticator را روی گوشی باز کنید و گزینهٔ افزودن حساب با کلید تنظیم را بزنید.")}
          {step(2, "این کلید را در برنامه وارد کنید:", <>
            <code className="block break-all border border-[color:var(--line)] bg-white p-3 text-sm" dir="ltr">{secret}</code>
            <a href={uri} className="inline-block text-sm text-brand-600 underline">باز کردن در برنامه آتنتیکیتور</a>
          </>)}
          {step(3, "کد شش‌رقمی نمایش‌داده‌شده را وارد و تأیید کنید.", <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
            <div className="w-48">{codeField("totp-code", "کد شش‌رقمی برنامه")}</div>
            <button className="btn" disabled={busy}>تأیید و فعال‌سازی</button>
          </form>)}
        </ol> : <div className="space-y-4">
          <ul className="space-y-2 text-sm leading-7">
            <li className="flex gap-2"><span className="mt-2.5 h-1.5 w-1.5 shrink-0 bg-[#4B6E48]" aria-hidden="true" />حساب مدیر سازمان در برابر لو رفتن گذرواژه محافظت می‌شود.</li>
            <li className="flex gap-2"><span className="mt-2.5 h-1.5 w-1.5 shrink-0 bg-[#4B6E48]" aria-hidden="true" />راه‌اندازی کمتر از یک دقیقه طول می‌کشد.</li>
          </ul>
          <button className="btn" disabled={busy} onClick={start}>فعال‌سازی ورود دومرحله‌ای</button>
        </div>}
      </div>
      <img className="mx-auto hidden w-full max-w-xs mix-blend-multiply opacity-95 lg:block" src={twoFactorArt} alt="" aria-hidden="true" loading="lazy" decoding="async" />
    </div>
  </section>;
}
