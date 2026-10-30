import { Icon } from "./SiteIcon";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { isCompleteOtp } from "@cbi/web-shared/lib/otp";
import { fmt, request } from "../api";
import type { TokenPair } from "../types";
import "./quick-demo.css";

interface Account { user_id: string; organization_name: string; requires_totp: boolean; active: boolean }
interface PendingAuth {
  mobile: string; otpId: string; expiresAt: number; resendAt: number;
  grant: string; accounts: Account[]; verifiedAt: number;
}
const EMPTY: PendingAuth = { mobile: "", otpId: "", expiresAt: 0, resendAt: 0, grant: "", accounts: [], verifiedAt: 0 };
const STORAGE = "sedasanj.phone-auth";

function localMobileNumber(value: string) {
  const digits = fmt.latinDigits(value).replace(/\D/g, "");
  if (digits.startsWith("0098")) return `0${digits.slice(4)}`;
  if (digits.startsWith("98")) return `0${digits.slice(2)}`;
  return digits;
}

function OtpDigits({ value, onChange, autoFocus, label }: { value: string; onChange: (value: string) => void; autoFocus?: boolean; label: string }) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  function enterDigits(index: number, rawValue: string) {
    const digits = fmt.latinDigits(rawValue).replace(/\D/g, "");
    if (!digits) {
      const next = value.split("");
      next[index] = "";
      onChange(next.join(""));
      return;
    }
    const next = value.padEnd(6, " ").split("");
    digits.slice(0, 6 - index).split("").forEach((digit, offset) => { next[index + offset] = digit; });
    onChange(next.join("").replace(/ /g, ""));
    refs.current[Math.min(index + digits.length, 5)]?.focus();
  }
  return <div className="demo-otp-inputs" role="group" aria-label={label} dir="ltr">
    {Array.from({ length: 6 }, (_, index) => <input
      key={index}
      ref={(element) => { refs.current[index] = element; }}
      type="text"
      inputMode="numeric"
      autoComplete={index === 0 ? "one-time-code" : "off"}
      autoFocus={autoFocus && index === 0}
      aria-label={`رقم ${index + 1} از ۶`}
      value={value[index] || ""}
      onChange={(event) => enterDigits(index, event.target.value)}
      onPaste={(event) => { event.preventDefault(); enterDigits(index, event.clipboardData.getData("text")); }}
      onKeyDown={(event) => {
        if (event.key === "Backspace" && !value[index] && index > 0) refs.current[index - 1]?.focus();
        if (event.key === "ArrowLeft" && index < 5) refs.current[index + 1]?.focus();
        if (event.key === "ArrowRight" && index > 0) refs.current[index - 1]?.focus();
      }}
    />)}
  </div>;
}

function restore(): PendingAuth {
  try {
    const value = JSON.parse(sessionStorage.getItem(STORAGE) || "null") as PendingAuth | null;
    if (value && (value.expiresAt > Date.now() || value.verifiedAt + 600000 > Date.now())) return value;
  } catch { /* Ignore stale browser state. */ }
  return { ...EMPTY };
}

export default function PhoneAuth({ onSuccess, renderArtwork }: { onSuccess: (pair: TokenPair) => void; renderArtwork?: (step: "phone" | "code" | "organization") => React.ReactNode }) {
  const [, setParams] = useSearchParams();
  const [pending, setPending] = useState<PendingAuth>(restore);
  const [code, setCode] = useState("");
  const [organization, setOrganization] = useState("");
  const [selected, setSelected] = useState("");
  const [totp, setTotp] = useState("");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now());
  const autoSubmittedOtp = useRef("");
  const step = pending.grant ? "organization" : pending.otpId ? "code" : "phone";
  const account = pending.accounts.find((item) => item.user_id === selected) || pending.accounts[0];
  useEffect(() => {
    sessionStorage.setItem(STORAGE, JSON.stringify(pending));
    setParams((current) => {
      if (current.get("authStep") === step) return current;
      const next = new URLSearchParams(current); next.set("authStep", step); return next;
    }, { replace: true });
  }, [pending, step, setParams]);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  useEffect(() => {
    const value = step === "code" ? code : step === "organization" && account?.requires_totp ? totp : "";
    if (!isCompleteOtp(value)) {
      autoSubmittedOtp.current = "";
      return;
    }
    const key = `${step}:${account?.user_id || ""}:${value}`;
    if (busy || autoSubmittedOtp.current === key) return;
    autoSubmittedOtp.current = key;
    void executeSubmit();
  }, [account?.requires_totp, account?.user_id, busy, code, step, totp]);

  async function finish(grant: string, userId?: string, name?: string) {
    setCreating(!userId);
    try {
      const pair = await request<TokenPair>("/v1/auth/phone/complete", { method: "POST", retry: false,
        body: { verified_token: grant, user_id: userId || undefined,
          organization_name: name || undefined, totp_code: totp || undefined } });
      sessionStorage.removeItem(STORAGE);
      onSuccess(pair);
    } finally { setCreating(false); }
  }
  async function sendCode() {
    const result = await request<{ otp_id: string; expires_in: number; resend_after: number }>("/v1/auth/phone/request", {
      method: "POST", retry: false, body: { mobile: pending.mobile },
    });
    setPending({ ...EMPTY, mobile: pending.mobile, otpId: result.otp_id,
      expiresAt: Date.now() + result.expires_in * 1000, resendAt: Date.now() + result.resend_after * 1000 });
    setCode("");
  }
  async function executeSubmit() {
    if (busy) return;
    if (step === "phone" && !pending.mobile.trim()) { setError("شماره موبایل را وارد کنید."); return; }
    if (step === "code" && code.length !== 6) { setError("کد شش‌رقمی را کامل وارد کنید."); return; }
    if (step === "organization" && account?.requires_totp && totp.length !== 6) { setError("کد ورود دومرحله‌ای را کامل وارد کنید."); return; }
    if (step === "organization" && !pending.accounts.length && organization.trim().length < 2) { setError("نام سازمان باید دست‌کم دو نویسه باشد."); return; }
    setBusy(true); setError("");
    try {
      if (step === "phone") await sendCode();
      else if (step === "code") {
        const result = await request<{ verified_token: string; accounts: Account[] }>("/v1/auth/phone/verify", {
          method: "POST", retry: false, body: { otp_id: pending.otpId, code },
        });
        setPending((current) => ({ ...current, grant: result.verified_token, accounts: result.accounts, verifiedAt: Date.now() }));
        setSelected(result.accounts[0]?.user_id || "");
        if (result.accounts.length === 1 && !result.accounts[0].requires_totp && result.accounts[0].active)
          await finish(result.verified_token, result.accounts[0].user_id);
      } else {
        await finish(pending.grant, account?.user_id, organization.trim());
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "درخواست انجام نشد؛ دوباره تلاش کنید."); }
    finally { setBusy(false); }
  }
  function submit(event: React.FormEvent) {
    event.preventDefault();
    void executeSubmit();
  }
  async function resend() {
    setBusy(true); setError("");
    try { await sendCode(); } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  function reset() { setPending({ ...EMPTY, mobile: pending.mobile }); setCode(""); setTotp(""); setError(""); }
  const expiresIn = Math.max(0, Math.ceil((pending.expiresAt - now) / 1000));
  if (creating) return <div className="demo-progress" role="status"><span className="demo-spinner"/><h3>در حال ایجاد حساب سازمانی دمو</h3><p>فضای سازمان و پلن آزمایشی شما آماده می‌شود…</p></div>;
  if (busy && step === "organization") return <div className="demo-progress" role="status"><span className="demo-spinner"/><h3>در حال ورود به سازمان</h3><p>حساب سازمانی شما در حال آماده‌سازی است…</p></div>;
  return <form className={`demo-phone-form${step === "code" && renderArtwork ? " has-otp-artwork" : ""}`} onSubmit={submit} noValidate dir="rtl">
    {renderArtwork?.(step)}
    <h2>{step === "phone" ? "" : step === "code" ? "تأیید شماره موبایل" : pending.accounts.length ? "ورود به سازمان" : "نام سازمان شما چیست؟"}</h2>
    {step !== "phone" && <p className={step === "code" ? "demo-code-hint" : undefined}>{step === "code" ? `کد ارسال‌شده به ${fmt.digits(localMobileNumber(pending.mobile))} را وارد کنید.` : pending.accounts.length ? "حساب موجود شما آماده ورود است." : "پلن دمو به‌صورت خودکار برای سازمان شما فعال می‌شود."}</p>}
    {error && <p className="demo-error" role="alert">{error}</p>}
    {step === "phone" && <label>شماره موبایل<input autoFocus type="tel" inputMode="tel" autoComplete="tel" dir="ltr" placeholder="09121234567" required value={pending.mobile} onChange={(e) => setPending({ ...pending, mobile: fmt.latinDigits(e.target.value) })}/></label>}
    {step === "code" && <label>کد شش‌رقمی<OtpDigits value={code} onChange={setCode} autoFocus label="کد شش‌رقمی"/></label>}
    {step === "organization" && (pending.accounts.length ? <>
      <label>سازمان<select value={account?.user_id || ""} onChange={(e) => { setSelected(e.target.value); setTotp(""); }}>{pending.accounts.map((item) => <option key={item.user_id} value={item.user_id}>{item.organization_name}{item.active ? "" : " (غیرفعال)"}</option>)}</select></label>
      {account?.requires_totp && <label>کد ورود دومرحله‌ای<OtpDigits value={totp} onChange={setTotp} autoFocus label="کد ورود دومرحله‌ای"/></label>}
    </> : <label>نام سازمان<input autoFocus autoComplete="organization" required minLength={2} maxLength={200} value={organization} onChange={(e) => setOrganization(e.target.value)}/></label>)}
    <button className="demo-button" disabled={busy || (step === "code" && !expiresIn) || (step === "organization" && account && !account.active)}>{busy ? "لطفاً صبر کنید…" : step === "phone" ? <><Icon name="message" size={18}/>دریافت کد تأیید</> : step === "code" ? <><Icon name="check" size={18}/>تأیید و ادامه</> : pending.accounts.length ? <><Icon name="login" size={18}/>ورود</> : <><Icon name="userPlus" size={18}/>ایجاد حساب دمو</>}</button>
    {step !== "phone" && <div className="demo-inline-actions"><button type="button" disabled={busy} onClick={reset}><Icon name="back" size={18}/>تغییر شماره / شروع دوباره</button>{step === "code" && (expiresIn ? <button className="demo-resend-countdown" type="button" disabled><svg aria-hidden="true" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg><span>{fmt.int(expiresIn)} ثانیه</span></button> : <button className="demo-resend-link" type="button" disabled={busy} onClick={() => void resend()}><Icon name="refresh" size={18}/>ارسال دوباره کد</button>)}</div>}
    <small>با ادامه، <a href="/terms" target="_blank" rel="noreferrer">قوانین استفاده</a> و <a href="/privacy" target="_blank" rel="noreferrer">حریم خصوصی</a> را می‌پذیرید.</small>
  </form>;
}
