import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { isCompleteOtp, normalizeOtp } from "@cbi/web-shared/lib/otp";
import { ApiError, fmt, request } from "../api";
import { useAuth } from "../auth";
import { ErrorBox } from "../components/Widgets";
import { BrandLogo } from "../components/BrandLogo";
import PhoneAuth from "../components/PhoneAuth";

export default function Login() {
  const { login, acceptSession } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const method = params.get("method") === "password" ? "password" : "phone";
  const next = params.get("next");
  const destination = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<"password" | "totp">("password");
  const autoSubmittedOtp = useRef("");

  async function authenticate() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (step === "password") {
        const result = await request<{ requires_totp: boolean }>("/v1/auth/check", { method: "POST", body: { email, password }, retry: false });
        if (result.requires_totp) { setStep("totp"); return; }
      }
      await login(email, password, totp);
      navigate(destination);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ورود ناموفق بود");
    } finally {
      setBusy(false);
    }
  }
  function submit(event: React.FormEvent) {
    event.preventDefault();
    void authenticate();
  }
  useEffect(() => {
    if (step !== "totp" || !isCompleteOtp(totp)) {
      autoSubmittedOtp.current = "";
      return;
    }
    if (busy || autoSubmittedOtp.current === totp) return;
    autoSubmittedOtp.current = totp;
    void authenticate();
  }, [busy, step, totp]);

  return (
    <main
      className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 px-4 py-8"
      style={{ backgroundImage: "radial-gradient(circle, rgb(75 110 72 / 0.18) 0 1px, transparent 1.15px)", backgroundPosition: "0 0", backgroundSize: "8px 8px" }}
    >
      <div className="relative w-full max-w-md">
        <div className="mb-5 flex w-full justify-center">
          <Link to="/" aria-label="صفحه اصلی">
            <BrandLogo animated className="block w-48 sm:w-56" title="صدا سنج" />
          </Link>
        </div>
        <section className="relative w-full overflow-hidden border border-brand-200 bg-white/90 p-4 shadow-2xl shadow-brand-950/10 backdrop-blur-sm sm:p-6">
          <div className="mx-auto max-w-sm">
            <div className="demo-device-tabs login-method-tabs" role="group" aria-label="روش ورود">{([['phone', 'شماره موبایل'], ['password', 'ایمیل و رمز']] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={method === value} onClick={() => setParams((current) => { const changed = new URLSearchParams(current); changed.set("method", value); return changed; }, { replace: true })}>{label}</button>)}</div>
            {method === "phone" ? <PhoneAuth onSuccess={(pair) => { acceptSession(pair); navigate(destination); }}/> : <>
            <form onSubmit={submit}>
              <ErrorBox message={error} />
              {step === "password" ? (<>
              <label className="label font-medium text-slate-700" htmlFor="email">
                ایمیل
              </label>
              <input
                id="email"
                className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white"
                type="email"
                dir="ltr"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
              <label className="label font-medium text-slate-700" htmlFor="password">
                گذرواژه
              </label>
              <input
                id="password"
                className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white"
                type="password"
                dir="ltr"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              </>) : (<>
              <label className="label font-medium text-slate-700" htmlFor="totp">
                کد گوگل آتنتیکیتور
              </label>
              <input
                id="totp"
                className="input mb-6 border-slate-200 bg-slate-50 py-2.5 focus:bg-white"
                dir="ltr"
                inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          required
                value={fmt.digits(totp)}
                onChange={(event) => setTotp(normalizeOtp(event.target.value))}
              />
              <button type="button" className="mb-4 text-sm text-brand-600" onClick={() => { setStep("password"); setTotp(""); setError(null); }}>بازگشت و ویرایش ایمیل یا گذرواژه</button>
              </>)}
              <button className="btn w-full py-3 font-bold shadow-lg shadow-brand-500/25" disabled={busy}>
                {busy ? "در حال ورود…" : step === "totp" ? "تأیید و ورود" : "ادامه"}
              </button>
              <p className="mt-5 text-center text-sm text-slate-500">حساب ندارید؟ <Link className="font-bold text-brand-600" to="/signup?plan=demo">دموی رایگان را شروع کنید</Link></p>
            </form>
            </>}
          </div>
        </section>
      </div>
    </main>
  );
}
