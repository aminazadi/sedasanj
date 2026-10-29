import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import { BrandLogo } from "../components/BrandLogo";
import { ErrorBox } from "../components/Widgets";
import planDemoImage from "../assets/plan-demo.webp";
import planBronzeImage from "../assets/plan-bronze.webp";
import planSilverImage from "../assets/plan-silver.webp";
import planGoldImage from "../assets/plan-gold.webp";

type Step = "identity" | "code" | "account";

const planDetails: Record<string, { name: string; image: string }> = {
  demo: { name: "دمو", image: planDemoImage },
  bronze: { name: "برنزی", image: planBronzeImage },
  silver: { name: "نقره‌ای", image: planSilverImage },
  gold: { name: "طلایی", image: planGoldImage },
};

const stepNumber: Record<Step, number> = { identity: 1, code: 2, account: 3 };

export default function Signup() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const requestedPlan = params.get("plan") ?? "demo";
  const plan = ["demo", "bronze", "silver", "gold"].includes(requestedPlan)
    ? requestedPlan
    : "demo";
  const selectedPlan = planDetails[plan];
  const [step, setStep] = useState<Step>("identity");
  const [otpId, setOtpId] = useState("");
  const [developmentCode, setDevelopmentCode] = useState("");
  const [form, setForm] = useState({
    organization_name: "",
    manager_name: "",
    email: "",
    mobile: "",
    password: "",
    code: "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (step === "identity") {
        const result = await request<{ otp_id: string; development_code?: string }>(
          "/v1/signup/otp/request",
          { method: "POST", body: { email: form.email, mobile: form.mobile }, retry: false },
        );
        setOtpId(result.otp_id);
        setDevelopmentCode(result.development_code ?? "");
        setStep("code");
      } else if (step === "code") {
        await request("/v1/signup/otp/verify", {
          method: "POST",
          body: { otp_id: otpId, code: fmt.latinDigits(form.code) },
          retry: false,
        });
        setStep("account");
      } else {
        const result = await request<{ requires_payment: boolean }>("/v1/signup/complete", {
          method: "POST",
          body: { ...form, code: undefined, otp_id: otpId, plan_code: plan },
          retry: false,
        });
        navigate(
          result.requires_payment
            ? `/login?next=${encodeURIComponent(`/checkout?plan=${plan}`)}`
            : "/login?registered=1",
        );
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "ثبت‌نام انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  return <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 px-4 py-8" dir="rtl" style={{ backgroundImage: "radial-gradient(circle, rgb(75 110 72 / 0.18) 0 1px, transparent 1.15px)", backgroundPosition: "0 0", backgroundSize: "8px 8px" }}>
    <div className="relative w-full max-w-md">
      <div className="mb-5 flex w-full justify-center"><Link to="/" aria-label="صفحه اصلی"><BrandLogo animated className="block w-48 sm:w-56" title="صدا سنج" /></Link></div>
      <section className="relative w-full overflow-hidden border border-brand-200 bg-white/90 p-4 shadow-2xl shadow-brand-950/10 backdrop-blur-sm sm:p-6">
        <div className="mx-auto max-w-sm">
          <div className="mb-5 flex items-center gap-4 border-b border-slate-100 pb-5">
            <img className="h-24 w-24 shrink-0 object-contain" src={selectedPlan.image} alt={`تصویر پلن ${selectedPlan.name}`} />
            <div><span className="text-xs font-bold text-brand-600">ثبت‌نام پلن {selectedPlan.name}</span><h1 className="mt-2 text-xl font-bold text-brand-800">حساب سازمانی خود را بسازید</h1><p className="mt-2 text-xs leading-6 text-slate-500">مرحله {fmt.digits(stepNumber[step])} از ۳</p></div>
          </div>
          <form onSubmit={submit}>
            <ErrorBox message={error || null} />
            {step === "identity" ? <>
              <label className="label font-medium text-slate-700" htmlFor="signup-email">ایمیل سازمانی</label>
              <input id="signup-email" className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white" type="email" dir="ltr" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
              <label className="label font-medium text-slate-700" htmlFor="signup-mobile">شماره موبایل</label>
              <input id="signup-mobile" className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white" type="tel" dir="ltr" required placeholder="09121234567" value={form.mobile} onChange={(event) => setForm({ ...form, mobile: fmt.latinDigits(event.target.value) })} />
            </> : null}
            {step === "code" ? <>
              <label className="label font-medium text-slate-700" htmlFor="signup-code">کد شش‌رقمی</label>
              <input id="signup-code" className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white" inputMode="numeric" autoComplete="one-time-code" dir="ltr" required maxLength={6} value={form.code} onChange={(event) => setForm({ ...form, code: fmt.latinDigits(event.target.value).replace(/\D/g, "") })} />
              {developmentCode ? <small className="mb-4 block text-xs text-slate-500">کد محیط توسعه: {fmt.digits(developmentCode)}</small> : null}
            </> : null}
            {step === "account" ? <>
              <label className="label font-medium text-slate-700" htmlFor="organization-name">نام سازمان</label>
              <input id="organization-name" className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white" required value={form.organization_name} onChange={(event) => setForm({ ...form, organization_name: event.target.value })} />
              <label className="label font-medium text-slate-700" htmlFor="manager-name">نام مدیر سازمان</label>
              <input id="manager-name" className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white" required value={form.manager_name} onChange={(event) => setForm({ ...form, manager_name: event.target.value })} />
              <label className="label font-medium text-slate-700" htmlFor="signup-password">گذرواژه</label>
              <input id="signup-password" className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white" type="password" dir="ltr" minLength={8} required value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />
            </> : null}
            <button className="btn w-full py-3 font-bold shadow-lg shadow-brand-500/25" disabled={busy}>{busy ? "در حال انجام…" : step === "identity" ? "ارسال کد تأیید" : step === "code" ? "تأیید کد" : "ساخت حساب"}</button>
            <p className="mt-5 text-center text-sm text-slate-500">حساب دارید؟ <Link className="font-bold text-brand-600" to="/login">وارد شوید</Link></p>
          </form>
        </div>
      </section>
    </div>
  </main>;
}
