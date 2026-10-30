import { cssUrl } from "../../../shared/lib/cssUrl";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { isCompleteOtp, normalizeOtp } from "@cbi/web-shared/lib/otp";
import { ApiError, fmt, request } from "../api";
import { useAuth } from "../auth";
import { ErrorBox } from "../components/Widgets";
import logo from "../assets/logo-small-fa.webp";
import pattern from "../assets/pattern.webp";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [totp, setTotp] = useState("");
  const [step, setStep] = useState<"password" | "totp">("password");
  const autoSubmittedOtp = useRef("");

  async function authenticate() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (step === "password") {
        const result = await request<{ requires_totp: boolean }>("/v1/admin/auth/check", {
          method: "POST", body: { email, password }, retry: false,
        });
        if (result.requires_totp) {
          setStep("totp");
          return;
        }
      }
      await login(email, password, totp);
      navigate("/");
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
      className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-100 px-4 py-8"
      style={{ backgroundImage: cssUrl(pattern), backgroundPosition: "center", backgroundSize: "cover" }}
    >
      <div className="absolute inset-0 bg-slate-950/10" />
      <form
        onSubmit={submit}
        className="relative w-full max-w-md rounded-3xl border border-white/80 bg-white/95 p-7 shadow-2xl shadow-slate-950/10 backdrop-blur-sm sm:p-10"
      >
        <img className="mb-8 h-12 w-auto" src={logo} alt="صدا سنج" />
        <div className="mb-8 border-r-4 border-brand-500 pr-3">
          <h1 className="text-2xl font-bold text-slate-900">ورود به پنل</h1>
        </div>
        <ErrorBox message={error} />
        {step === "password" ? <><label className="label font-medium text-slate-700" htmlFor="email">
          ایمیل
        </label>
        <input
          id="email"
          className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white"
          type="text"
          autoComplete="username"
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
        </> : <>
        <label className="label font-medium text-slate-700" htmlFor="totp">کد گوگل آتنتیکیتور</label>
        <input
          id="totp"
          className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white"
          type="text"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          dir="ltr"
          value={fmt.digits(totp)}
          onChange={(event) => setTotp(normalizeOtp(event.target.value))}
          autoFocus
          required
        />
        <button type="button" className="mb-4 text-sm text-brand-600" onClick={() => { setStep("password"); setTotp(""); setError(null); }}>بازگشت و ویرایش ایمیل یا گذرواژه</button>
        </>}
        <button className="btn w-full py-3 font-bold shadow-lg shadow-brand-500/25" disabled={busy}>
          {busy ? "…" : step === "totp" ? "تأیید و ورود" : "ادامه"}
        </button>
      </form>
    </main>
  );
}
