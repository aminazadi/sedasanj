import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import { useAuth } from "../auth";
import { ErrorBox } from "../components/Widgets";
import logo from "../assets/sedasanj-refined-master.svg";

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
      style={{ backgroundImage: "radial-gradient(circle, rgb(75 110 72 / 0.18) 0 1px, transparent 1.15px)", backgroundPosition: "0 0", backgroundSize: "8px 8px" }}
    >
      <section className="relative w-full max-w-md overflow-hidden rounded-3xl border border-white/80 bg-white/90 p-6 shadow-2xl shadow-brand-950/10 backdrop-blur-sm sm:p-10">
          <div className="mx-auto max-w-sm">
            <img className="mx-auto mb-7 h-12 w-auto" src={logo} alt="صدا سنج" />
            <h2 className="text-center text-2xl font-bold text-slate-900">خوش آمدید</h2>
            <p className="mt-2 mb-8 text-center text-sm text-slate-500">برای ورود به پنل، اطلاعات خود را وارد کنید.</p>
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
      </section>
    </main>
  );
}
