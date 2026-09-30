import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import { useAuth } from "../auth";
import { ErrorBox } from "../components/Widgets";
import logo from "../assets/logo-small-fa.png";
import pattern from "../assets/pattern.png";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [step, setStep] = useState<"password" | "totp">("password");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (step === "password") {
        const result = await request<{ requires_totp: boolean }>("/v1/admin/auth/check", { method: "POST", body: { email, password }, retry: false });
        if (result.requires_totp) { setStep("totp"); return; }
      }
      await login(email, password, totp);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ورود ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-100 px-4 py-8"
      style={{ backgroundImage: `url(${pattern})`, backgroundPosition: "center", backgroundSize: "cover" }}
    >
      <div className="absolute inset-0 bg-slate-950/10" />
      <form
        onSubmit={submit}
        className="relative w-full max-w-md rounded-3xl border border-white/80 bg-white/95 p-7 shadow-2xl shadow-slate-950/10 backdrop-blur-sm sm:p-10"
      >
        <img className="mb-8 h-12 w-auto" src={logo} alt="صدا سنج" />
        <div className="mb-8 border-r-4 border-brand-500 pr-3">
          <h1 className="text-2xl font-bold text-slate-900">ورود کارکنان</h1>
          <p className="mt-1 text-sm text-slate-500">دسترسی محدود به تیم پلتفرم</p>
        </div>
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
          onChange={(event) => setTotp(fmt.latinDigits(event.target.value).replace(/\D/g, "").slice(0, 6))}
        />
        <button type="button" className="mb-4 text-sm text-brand-600" onClick={() => { setStep("password"); setTotp(""); setError(null); }}>بازگشت و ویرایش ایمیل یا گذرواژه</button>
        </>)}
        <button className="btn w-full py-3 font-bold shadow-lg shadow-brand-500/25" disabled={busy}>
          {busy ? "…" : step === "totp" ? "تأیید و ورود" : "ادامه"}
        </button>
      </form>
    </main>
  );
}
