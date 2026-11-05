import { useEffect, useRef, useState, type FormEvent } from "react";
import { isCompleteOtp, normalizeOtp } from "@cbi/web-shared/lib/otp";
import { ApiError, request } from "../api";
import { useAuth } from "../auth";
import type { TokenPair } from "../types";
import { ErrorBox } from "./Widgets";
import passwordArt from "../assets/password-change.svg";
import OtpDigits from "./OtpDigits";

const clock = new Intl.NumberFormat("fa-IR", { minimumIntegerDigits: 2, useGrouping: false });

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

  const [remaining, setRemaining] = useState(0);
  const [total, setTotal] = useState(0);
  const autoSubmittedOtp = useRef("");
  const verifying = useRef(false);

  useEffect(() => {
    if (!isCompleteOtp(code)) {
      autoSubmittedOtp.current = "";
      return;
    }
    const key = `${otp?.otp_id}:${code}`;
    if (!otp || grant || busy || autoSubmittedOtp.current === key) return;
    autoSubmittedOtp.current = key;
    void verifyCode();
  }, [code, otp, grant, busy]);

  useEffect(() => {
    if (!resendAt) {
      setRemaining(0);
      return;
    }
    const tick = () => {
      const left = Math.max(0, Math.ceil((resendAt - Date.now()) / 1000));
      setRemaining(left);
      if (left === 0) setResendAt(0);
    };
    tick();
    const timer = window.setInterval(tick, 500);
    return () => window.clearInterval(timer);
  }, [resendAt]);

  async function sendCode() {
    if (busy || resendAt > Date.now()) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const result = await request<PasswordOtp>("/v1/auth/phone/password/request", { method: "POST" });
      setOtp(result);
      setCode("");
      setGrant("");
      setTotp("");
      setPassword("");
      setConfirmation("");
      autoSubmittedOtp.current = "";
      setTotal(result.resend_after);
      setResendAt(Date.now() + result.resend_after * 1000);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function verifyCode() {
    if (!otp || grant || busy || verifying.current || !isCompleteOtp(code)) return;
    verifying.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await request<{ verified_token: string }>("/v1/auth/phone/verify", {
        method: "POST",
        retry: false,
        body: { otp_id: otp.otp_id, code },
      });
      setGrant(result.verified_token);
      setCode("");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      verifying.current = false;
      setBusy(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!otp || !grant || busy) return;
    if (password !== confirmation) {
      setError("گذرواژهٔ جدید و تکرار آن باید یکسان باشند.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const pair = await request<TokenPair>("/v1/auth/phone/password/change", {
        method: "POST",
        retry: false,
        body: { verified_token: grant, new_password: password, totp_code: totp || null },
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
        setCode("");
        setPassword("");
        setConfirmation("");
        setTotp("");
      }
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="card" aria-labelledby="password-change-title">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 id="password-change-title" className="font-bold">تغییر گذرواژه</h2>
    </div>
    <ErrorBox message={error} />
    <div className="grid items-center gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="min-w-0 space-y-5">
        <p className="text-sm leading-7 text-slate-500">{mobile ? <>کد تأیید به شمارهٔ <bdi dir="ltr">{mobile}</bdi> ارسال می‌شود.</> : "برای دریافت کد تأیید، ابتدا شماره موبایل را در پروفایل ذخیره کنید."}</p>
        {saved ? <p className="form-success" role="status">گذرواژه تغییر کرد.</p> : null}
        {mobile && !grant ? <div className="password-otp-bar">
          {otp && remaining > 0 ? <div className="password-timer" role="timer" aria-live="off">
            <svg className="password-timer-ring" viewBox="0 0 56 56" aria-hidden="true" focusable="false">
              <circle className="password-timer-track" cx="28" cy="28" r="25" />
              <circle className="password-timer-progress" cx="28" cy="28" r="25" pathLength="100" strokeDasharray="100" strokeDashoffset={100 * (1 - Math.min(1, Math.max(0, total ? remaining / total : 0)))} />
            </svg>
            <span className="password-timer-text"><bdi dir="ltr">{clock.format(Math.floor(remaining / 60))}:{clock.format(remaining % 60)}</bdi></span>
          </div> : null}
          <button type="button" className={otp ? "btn-ghost" : "btn"} disabled={busy || remaining > 0} onClick={() => void sendCode()}>
            {otp ? (remaining > 0 ? "ارسال دوباره پس از پایان زمان" : "ارسال دوباره کد") : "ارسال کد تأیید"}
          </button>
        </div> : null}
        {otp && !grant ? <form className="max-w-sm space-y-4" onSubmit={(event) => { event.preventDefault(); void verifyCode(); }}>
          <fieldset disabled={busy} className="space-y-3">
            <p className="label">کد شش‌رقمی پیامک را وارد کنید.</p>
            <OtpDigits value={code} onChange={setCode} autoFocus label="کد شش‌رقمی پیامک" />
            <button className="btn" disabled={busy || !isCompleteOtp(code)}>{busy ? "در حال تأیید…" : "تأیید کد"}</button>
          </fieldset>
        </form> : null}
        {otp && grant ? <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <fieldset className="grid gap-4 md:grid-cols-2" disabled={busy}>
            {otp.requires_totp ? <label>
              <span className="label">کد ورود دومرحله‌ای</span>
              <input className="input" dir="ltr" inputMode="numeric" pattern="[0-9]{6}" value={totp} onChange={(event) => setTotp(normalizeOtp(event.target.value))} required />
            </label> : null}
            <label>
              <span className="label">گذرواژهٔ جدید (حداقل ۸ نویسه)</span>
              <input className="input" type="password" dir="ltr" autoComplete="new-password" autoFocus minLength={8} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} required />
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
      </div>
      <img className="mx-auto hidden w-full max-w-xs mix-blend-multiply opacity-95 lg:block" src={passwordArt} alt="" aria-hidden="true" loading="lazy" decoding="async" />
    </div>
  </section>;
}
