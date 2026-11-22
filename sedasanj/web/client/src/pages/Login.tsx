import { Icon } from "../components/SiteIcon";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { isCompleteOtp, normalizeOtp } from "@cbi/web-shared/lib/otp";
import { ApiError, fmt, request } from "../api";
import { useAuth } from "../auth";
import { ErrorBox } from "../components/Widgets";
import AuthShell from "../components/AuthShell";
import PhoneAuth from "../components/PhoneAuth";

export default function Login() {
  const { login, acceptSession } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const method = params.get("method") === "password" ? "password" : "phone";
  const next = params.get("next");
  const destination = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  const [identifier, setIdentifier] = useState("");
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
        const result = await request<{ requires_totp: boolean }>("/v1/auth/check", { method: "POST", body: { identifier, password }, retry: false });
        if (result.requires_totp) { setStep("totp"); return; }
      }
      await login(identifier, password, totp);
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
  function switchMethod(value: "phone" | "password") {
    setParams((current) => { const changed = new URLSearchParams(current); changed.set("method", value); return changed; }, { replace: true });
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
    <AuthShell>
          <div className="auth-form">
            {method === "phone" ? <>
            <PhoneAuth onSuccess={(pair) => { acceptSession(pair); navigate(destination); }}/>
            <p className="auth-alt mt-5 text-center text-sm text-slate-500">حساب با گذرواژه دارید؟ <button type="button" className="font-bold text-brand-600" onClick={() => switchMethod("password")}>ورود با گذرواژه</button></p>
            </> : <>
            <form onSubmit={submit}>
              <ErrorBox message={error} />
              {step === "password" ? (<>
              <label className="label" htmlFor="login-identifier">
                ایمیل یا شماره موبایل
              </label>
              <input
                id="login-identifier"
                className="input mb-4"
                type="text"
                dir="ltr"
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                value={identifier}
                onChange={(event) => setIdentifier(event.target.value)}
                maxLength={320}
                required
              />
              <label className="label" htmlFor="password">
                گذرواژه
              </label>
              <input
                id="password"
                className="input mb-4"
                type="password"
                autoComplete="current-password"
                dir="ltr"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              </>) : (<>
              <label className="label" htmlFor="totp">
                کد گوگل آتنتیکیتور
              </label>
              <input
                id="totp"
                className="input mb-6"
                dir="ltr"
                inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          required
                value={fmt.digits(totp)}
                onChange={(event) => setTotp(normalizeOtp(event.target.value))}
              />
              <button type="button" className="mb-4 text-sm text-brand-600" onClick={() => { setStep("password"); setTotp(""); setError(null); }}><Icon name="back" size={18}/>بازگشت و ویرایش اطلاعات ورود</button>
              </>)}
              <button className="btn w-full py-3 font-bold" disabled={busy}>
                {busy ? "در حال ورود…" : step === "totp" ? <><Icon name="login" size={18}/>تأیید و ورود</> : <>ادامه<Icon name="arrow" size={18}/></>}
              </button>
              <p className="auth-alt mt-5 text-center text-sm text-slate-500">حساب ندارید؟ <Link className="font-bold text-brand-600" to="/signup?plan=demo">دموی رایگان را شروع کنید</Link></p>
            </form>
            <p className="auth-alt mt-3 text-center text-sm text-slate-500">ترجیح می‌دهید کد یکبارمصرف دریافت کنید؟ <button type="button" className="font-bold text-brand-600" onClick={() => switchMethod("phone")}>ورود با کد پیامکی</button></p>
            </>}
          </div>
    </AuthShell>
  );
}
