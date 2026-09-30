import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import { useAuth } from "../auth";
import { ErrorBox } from "../components/Widgets";
import logo from "../assets/logo-small-fa.png";
import pattern from "../assets/pattern.png";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
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
        const result = await request<{ requires_totp: boolean }>("/v1/auth/check", { method: "POST", body: { email, password }, retry: false });
        if (result.requires_totp) { setStep("totp"); return; }
      }
      await login(email, password, totp);
      navigate(params.get("next") || "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ورود ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 px-4 py-8"
      style={{ backgroundImage: `url(${pattern})`, backgroundPosition: "center", backgroundSize: "cover" }}
    >
      <div className="absolute inset-0 bg-white/45" />
      <section className="relative grid w-full max-w-5xl overflow-hidden rounded-3xl border border-white/80 bg-white/90 shadow-2xl shadow-brand-950/10 backdrop-blur-sm lg:grid-cols-[1fr_1.1fr]">
        <div className="hidden flex-col justify-between bg-brand-600 p-10 text-white lg:flex">
          <div>
            <img className="h-14 w-auto rounded-xl bg-white px-3 py-2" src={logo} alt="صدا سنج" />
            <h1 className="mt-12 text-3xl font-bold leading-relaxed">تحلیل هوشمند مکالمات، در یک نگاه</h1>
            <p className="mt-4 max-w-sm text-sm leading-7 text-brand-100">
              به پنل سازمان یا پنل اپراتور وارد شوید و کیفیت، روند و نتیجه تماس‌ها را دنبال کنید.
            </p>
          </div>
          <p className="text-xs text-brand-100">سامانه تحلیل مکالمات صدا سنج</p>
        </div>
        <div className="p-6 sm:p-10">
          <div className="mx-auto max-w-sm">
            <img className="mb-8 h-12 w-auto lg:hidden" src={logo} alt="صدا سنج" />
            <h2 className="text-2xl font-bold text-slate-900">خوش آمدید</h2>
            <p className="mt-2 mb-8 text-sm text-slate-500">برای ورود به پنل، اطلاعات خود را وارد کنید.</p>
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
                onChange={(event) => setTotp(fmt.latinDigits(event.target.value).replace(/\D/g, "").slice(0, 6))}
              />
              <button type="button" className="mb-4 text-sm text-brand-600" onClick={() => { setStep("password"); setTotp(""); setError(null); }}>بازگشت و ویرایش ایمیل یا گذرواژه</button>
              </>)}
              <button className="btn w-full py-3 font-bold shadow-lg shadow-brand-500/25" disabled={busy}>
                {busy ? "در حال ورود…" : step === "totp" ? "تأیید و ورود" : "ادامه"}
              </button>
              <p className="mt-5 text-center text-sm text-slate-500">حساب ندارید؟ <Link className="font-bold text-brand-600" to="/signup?plan=demo">دموی رایگان را شروع کنید</Link></p>
            </form>
          </div>
        </div>
      </section>
    </main>
  );
}
