import { useEffect, useState, type FormEvent } from "react";
import { normalizeOtp } from "@cbi/web-shared/lib/otp";
import { ApiError, request } from "../api";
import { useAuth } from "../auth";
import type { TokenPair } from "../types";
import { ErrorBox } from "./Widgets";

type PasswordOtp = {
  otp_id: string;
  resend_after: number;
  requires_totp: boolean;
};

export default function PasswordChange({ mobile }: { mobile: string | null }) {
  const { acceptSession } = useAuth();
  const [otp, setOtp] = useState<PasswordOtp | null>(null);
  const [code, setCode] = useState("");
  const [grant, setGrant] = useState("");
  const [totp, setTotp] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [resendAt, setResendAt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!resendAt) return;
    const timer = window.setTimeout(() => setResendAt(0), Math.max(0, resendAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [resendAt]);

  async function sendCode() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const result = await request<PasswordOtp>("/v1/auth/phone/password/request", { method: "POST" });
      setOtp(result);
      setCode("");
      setGrant("");
      setTotp("");
      setResendAt(Date.now() + result.resend_after * 1000);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!otp || busy) return;
    if (password !== confirmation) {
      setError("گذرواژهٔ جدید و تکرار آن باید یکسان باشند.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      let verifiedToken = grant;
      if (!verifiedToken) {
        const result = await request<{ verified_token: string }>("/v1/auth/phone/verify", {
          method: "POST",
          retry: false,
          body: { otp_id: otp.otp_id, code },
        });
        verifiedToken = result.verified_token;
        setGrant(verifiedToken);
        setCode("");
      }
      const pair = await request<TokenPair>("/v1/auth/phone/password/change", {
        method: "POST",
        body: { verified_token: verifiedToken, new_password: password, totp_code: totp || null },
      });
      acceptSession(pair);
      setSaved(true);
      setOtp(null);
      setGrant("");
      setTotp("");
      setPassword("");
      setConfirmation("");
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "password_change_totp_required") {
        setOtp({ ...otp, requires_totp: true });
      }
      if (reason instanceof ApiError && reason.code === "password_change_verification_required") {
        setOtp(null);
        setGrant("");
      }
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="card space-y-4" aria-labelledby="password-change-title">
    <div>
      <h2 id="password-change-title" className="font-bold">تغییر گذرواژه</h2>
      <p className="section-hint">{mobile ? <>کد تأیید به شمارهٔ <bdi dir="ltr">{mobile}</bdi> ارسال می‌شود.</> : "برای دریافت کد تأیید، ابتدا شماره موبایل را در پروفایل ذخیره کنید."}</p>
    </div>
    <ErrorBox message={error} />
    {saved ? <p className="form-success" role="status">گذرواژه تغییر کرد.</p> : null}
    {mobile ? <button type="button" className={otp ? "btn-ghost" : "btn"} disabled={busy || Boolean(resendAt)} onClick={() => void sendCode()}>
      {otp ? "ارسال دوباره کد" : "ارسال کد تأیید"}
    </button> : null}
    {otp ? <form className="space-y-4" onSubmit={(event) => void submit(event)}>
      <fieldset className="grid gap-4 md:grid-cols-2" disabled={busy}>
        {!grant ? <label>
          <span className="label">کد شش‌رقمی پیامک</span>
          <input className="input" dir="ltr" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" value={code} onChange={(event) => setCode(normalizeOtp(event.target.value))} required />
        </label> : null}
        {otp.requires_totp ? <label>
          <span className="label">کد ورود دومرحله‌ای</span>
          <input className="input" dir="ltr" inputMode="numeric" pattern="[0-9]{6}" value={totp} onChange={(event) => setTotp(normalizeOtp(event.target.value))} required />
        </label> : null}
        <label>
          <span className="label">گذرواژهٔ جدید (حداقل ۸ نویسه)</span>
          <input className="input" type="password" dir="ltr" autoComplete="new-password" minLength={8} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} required />
        </label>
        <label>
          <span className="label">تکرار گذرواژهٔ جدید</span>
          <input className="input" type="password" dir="ltr" autoComplete="new-password" minLength={8} maxLength={256} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required />
        </label>
      </fieldset>
      <div className="form-actions">
        <button className="btn" disabled={busy}>{busy ? "لطفاً صبر کنید…" : "تغییر گذرواژه"}</button>
      </div>
    </form> : null}
  </section>;
}
