import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request } from "../api";
import logo from "../assets/logo-small-fa.png";

type Step = "identity" | "code" | "account";

export default function Signup() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const requestedPlan = params.get("plan") ?? "demo";
  const plan = ["demo", "bronze", "silver", "gold"].includes(requestedPlan)
    ? requestedPlan
    : "demo";
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

  return <main className="commerce-auth" dir="rtl"><section>
    <Link to="/"><img src={logo} alt="صداسنج" /></Link>
    <div className="commerce-auth-copy"><span>ثبت‌نام پلن {plan === "demo" ? "دمو" : plan}</span><h1>حساب سازمانی خود را بسازید</h1><p>تأیید موبایل، ساخت سازمان و فعال‌سازی پلن در یک مسیر امن انجام می‌شود.</p></div>
    {error ? <div className="commerce-error">{error}</div> : null}
    <form onSubmit={submit}>
      {step === "identity" ? <>
        <label>ایمیل سازمانی<input type="email" dir="ltr" required value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
        <label>شماره موبایل<input type="tel" dir="ltr" required placeholder="09121234567" value={form.mobile} onChange={(event) => setForm({ ...form, mobile: fmt.latinDigits(event.target.value) })} /></label>
      </> : null}
      {step === "code" ? <>
        <label>کد شش‌رقمی<input inputMode="numeric" dir="ltr" required maxLength={6} value={form.code} onChange={(event) => setForm({ ...form, code: fmt.latinDigits(event.target.value).replace(/\D/g, "") })} /></label>
        {developmentCode ? <small>کد محیط توسعه: {fmt.digits(developmentCode)}</small> : null}
      </> : null}
      {step === "account" ? <>
        <label>نام سازمان<input required value={form.organization_name} onChange={(event) => setForm({ ...form, organization_name: event.target.value })} /></label>
        <label>نام مدیر سازمان<input required value={form.manager_name} onChange={(event) => setForm({ ...form, manager_name: event.target.value })} /></label>
        <label>گذرواژه<input type="password" dir="ltr" minLength={8} required value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></label>
      </> : null}
      <button disabled={busy}>{busy ? "در حال انجام…" : step === "identity" ? "ارسال کد تأیید" : step === "code" ? "تأیید کد" : "ساخت حساب"}</button>
    </form>
    <p className="commerce-auth-foot">حساب دارید؟ <Link to="/login">وارد شوید</Link></p>
  </section></main>;
}
