import { useEffect, useState } from "react";
import { fmt, request } from "../api";

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

  return <section className="card space-y-4 p-5">
    <h2 className="font-bold">ورود دومرحله‌ای با گوگل آتنتیکیتور</h2>
    {error && <p role="alert" className="text-red-600">{error}</p>}
    {enabled === null ? <p>در حال بارگذاری…</p> : enabled ? <>
      <p>فعال است.</p>
      <form onSubmit={submit} className="space-y-3">
        <label className="label" htmlFor="totp-password">گذرواژه فعلی</label>
        <input id="totp-password" type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <label className="label" htmlFor="totp-code">کد گوگل آتنتیکیتور</label>
        <input id="totp-code" className="input" dir="ltr" inputMode="numeric" pattern="[0-9]{6}" value={fmt.digits(code)} onChange={(e) => setCode(fmt.latinDigits(e.target.value).replace(/\D/g, "").slice(0, 6))} required />
        <button className="btn" disabled={busy}>غیرفعال‌سازی</button>
      </form>
    </> : secret ? <>
      <p>در گوگل آتنتیکیتور گزینه افزودن حساب با کلید تنظیم را انتخاب کنید و این کلید را وارد کنید:</p>
      <code className="block break-all rounded bg-slate-100 p-3" dir="ltr">{secret}</code>
      <a href={uri} className="text-brand-600 underline">باز کردن در برنامه آتنتیکیتور</a>
      <form onSubmit={submit} className="space-y-3">
        <label className="label" htmlFor="totp-code">کد شش‌رقمی برنامه</label>
        <input id="totp-code" className="input" dir="ltr" inputMode="numeric" pattern="[0-9]{6}" value={fmt.digits(code)} onChange={(e) => setCode(fmt.latinDigits(e.target.value).replace(/\D/g, "").slice(0, 6))} required />
        <button className="btn" disabled={busy}>تأیید و فعال‌سازی</button>
      </form>
    </> : <button className="btn" disabled={busy} onClick={start}>فعال‌سازی ورود دومرحله‌ای</button>}
  </section>;
}
