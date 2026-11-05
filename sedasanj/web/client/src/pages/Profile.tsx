import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { normalizeOtp } from "@cbi/web-shared/lib/otp";
import { ApiError, fmt, request } from "../api";
import { ROLE_LABELS } from "../auth";
import PasswordChange from "../components/PasswordChange";
import TwoFactorSettings from "../components/TwoFactorSettings";
import { ErrorBox, Loading } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
import type { AccountInfo, User } from "../types";

type ProfileForm = {
  display_name: string;
  mobile_number: string;
  extension: string;
  profile_context: string;
};

const EMPTY_PROFILE: ProfileForm = {
  display_name: "",
  mobile_number: "",
  extension: "",
  profile_context: "",
};

/** UI-only comparison; the server decides whether the number really changed. */
function sameMobile(a: string, b: string): boolean {
  const digits = (value: string) => value
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/\D/g, "")
    .replace(/^0098/, "0")
    .replace(/^98/, "0")
    .replace(/^9(?=\d{9}$)/, "09");
  return digits(a) === digits(b);
}

export default function Profile() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [form, setForm] = useState<ProfileForm>(EMPTY_PROFILE);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [mobileOtp, setMobileOtp] = useState<{ otp_id: string; otp_mobile: string } | null>(null);
  const [mobileCode, setMobileCode] = useState("");
  const [mobileGrant, setMobileGrant] = useState("");
  const [sendingCode, setSendingCode] = useState(false);

  useEffect(() => {
    request<AccountInfo>("/v1/account")
      .then((value) => {
        setAccount(value);
        setForm({
          display_name: value.user.display_name || "",
          mobile_number: value.user.mobile_number || "",
          extension: value.user.extension || "",
          profile_context: value.user.profile_context || "",
        });
      })
      .catch((reason) => setError((reason as Error).message));
  }, []);

  const savedMobile = account?.user.mobile_number ?? "";
  const mobileChanged = !sameMobile(form.mobile_number, savedMobile);
  const newMobile = form.mobile_number.trim();

  async function sendMobileCode() {
    setSendingCode(true);
    setError(null);
    try {
      const result = await request<{ otp_id: string }>("/v1/auth/phone/request", {
        method: "POST",
        body: { mobile: newMobile },
      });
      setMobileOtp({ otp_id: result.otp_id, otp_mobile: newMobile });
      setMobileCode("");
      setMobileGrant("");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSendingCode(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      // Changing the number repoints login/password-reset codes, so it needs the current
      // password and proof (an SMS code) that the new number is yours.
      let verifiedToken = mobileGrant;
      if (mobileChanged && newMobile) {
        if (!mobileOtp || mobileOtp.otp_mobile !== newMobile) {
          throw new Error("برای شمارهٔ جدید ابتدا «ارسال کد تأیید» را بزنید.");
        }
        if (!verifiedToken) {
          const result = await request<{ verified_token: string }>("/v1/auth/phone/verify", {
            method: "POST",
            retry: false,
            body: { otp_id: mobileOtp.otp_id, code: mobileCode },
          });
          verifiedToken = result.verified_token;
          setMobileGrant(verifiedToken);
        }
      }
      const user = await request<User>("/v1/auth/me", {
        method: "PATCH",
        body: {
          display_name: form.display_name.trim(),
          mobile_number: newMobile || null,
          extension: form.extension.trim() || null,
          profile_context: form.profile_context.trim() || null,
          current_password: mobileChanged ? currentPassword : null,
          mobile_verified_token: mobileChanged && newMobile ? verifiedToken : null,
        },
      });
      setAccount((current) => current ? { ...current, user } : current);
      setForm((current) => ({ ...current, mobile_number: user.mobile_number || "" }));
      setCurrentPassword("");
      setMobileOtp(null);
      setMobileCode("");
      setMobileGrant("");
      setSaved(true);
    } catch (reason) {
      if (reason instanceof ApiError && reason.code === "mobile_change_verification_required") {
        setMobileOtp(null);
        setMobileGrant("");
      }
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!account && !error) return <Loading />;

  return (
    <div className="space-y-4">
      <PageHeader title="پروفایل من" description="مشخصات فردی، راه‌های تماس و امنیت ورود شما" />
      <ErrorBox message={error} />
      {account ? (
        <>
        <section className="card flex flex-wrap items-center justify-between gap-x-8 gap-y-5">
          <div className="flex min-w-0 items-center gap-4">
            <div className="flex h-16 w-16 shrink-0 items-center justify-center bg-[#4B6E48] text-2xl font-bold text-[#F2F0EF]" aria-hidden="true">{(account.user.display_name || account.user.email).slice(0, 1)}</div>
            <div className="min-w-0">
              <h2 className="truncate text-lg font-bold">{account.user.display_name || account.user.email}</h2>
              <p className="mt-0.5 break-all text-sm text-slate-500 [unicode-bidi:plaintext]" dir="ltr" style={{ textAlign: "right" }}>{account.user.email}</p>
            </div>
          </div>
          <dl className="grid grid-cols-3 gap-x-8 gap-y-3 text-sm max-sm:grid-cols-1">
            <div><dt className="text-xs text-slate-500">نقش</dt><dd className="mt-1 font-medium">{ROLE_LABELS[account.user.role] || account.user.role}</dd></div>
            <div><dt className="text-xs text-slate-500">سازمان</dt><dd className="mt-1 font-medium">{account.tenant.name}</dd></div>
            <div><dt className="text-xs text-slate-500">عضویت از</dt><dd className="mt-1 font-medium">{fmt.date(account.user.created_at)}</dd></div>
          </dl>
        </section>
        <form className="card space-y-5" onSubmit={submit}>
          <div><h2 className="font-bold">اطلاعات فردی</h2><p className="section-hint">این اطلاعات برای شناسایی شما و شخصی‌سازی دستیار استفاده می‌شود.</p></div>
          <div className="grid gap-4 md:grid-cols-2">
            <label>
              <span className="label">نام و نام خانوادگی</span>
              <input className="input" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} minLength={2} maxLength={120} autoComplete="name" required />
            </label>
            <label>
              <span className="label">ایمیل</span>
              <input className="input" value={account.user.email} dir="ltr" disabled />
            </label>
            <label>
              <span className="label">شماره موبایل</span>
              <input className="input" value={form.mobile_number} onChange={(event) => setForm({ ...form, mobile_number: event.target.value })} dir="ltr" inputMode="tel" autoComplete="tel" />
            </label>
            <label>
              <span className="label">شماره داخلی</span>
              <input className="input" value={form.extension} readOnly={account.user.role === "operator"} onChange={(event) => setForm({ ...form, extension: event.target.value })} dir="ltr" inputMode="numeric" />
            </label>
          </div>
          {mobileChanged ? (
            <fieldset className="grid gap-4 border-t border-[color:var(--line)] pt-5 md:grid-cols-2" disabled={saving}>
              <legend className="label">تأیید تغییر شمارهٔ موبایل</legend>
              <label>
                <span className="label">گذرواژهٔ فعلی</span>
                <input className="input" type="password" dir="ltr" autoComplete="current-password" maxLength={256} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required />
              </label>
              {newMobile ? (
                <div className="space-y-2">
                  <button type="button" className={mobileOtp ? "btn-ghost" : "btn"} disabled={sendingCode} onClick={() => void sendMobileCode()}>
                    {mobileOtp ? "ارسال دوباره کد" : "ارسال کد تأیید به شمارهٔ جدید"}
                  </button>
                  {mobileOtp ? (
                    <label className="block">
                      <span className="label">کد شش‌رقمی پیامک</span>
                      <input className="input" dir="ltr" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" value={mobileCode} onChange={(event) => setMobileCode(normalizeOtp(event.target.value))} required={!mobileGrant} />
                    </label>
                  ) : null}
                </div>
              ) : null}
            </fieldset>
          ) : null}
          <label className="block border-t border-[color:var(--line)] pt-5">
            <span className="label">درباره من و شیوه ارتباط دلخواه</span>
            <textarea
              className="input min-h-40 resize-y leading-7"
              value={form.profile_context}
              onChange={(event) => setForm({ ...form, profile_context: event.target.value })}
              maxLength={2000}
              placeholder="درباره مسئولیت‌ها، حوزه کاری، علایق حرفه‌ای و لحنی که ترجیح می‌دهید دستیار با شما صحبت کند بنویسید."
            />
            <span className="field-hint block text-left">{fmt.int(form.profile_context.length)} / {fmt.int(2000)}</span>
          </label>
          {account.user.role === "operator" ? <p className="field-hint">برای اپراتور ثبت حداقل یکی از شماره موبایل یا شماره داخلی الزامی است.</p> : null}
          <div className="form-actions">
            <button className="btn" disabled={saving}>{saving ? "در حال ذخیره…" : "ذخیره پروفایل"}</button>
            {saved ? <span className="form-success" role="status">پروفایل ذخیره شد.</span> : null}
          </div>
        </form>
        <PasswordChange key={account.user.mobile_number} mobile={account.user.mobile_number} />
        {account.user.role === "org_admin" ? <TwoFactorSettings /> : null}
        {account.user.role !== "operator" ? <nav className="card flex flex-wrap items-center gap-3" aria-label="بخش‌های مرتبط حساب"><Link className="btn-ghost" to="/account">اعتبار و اشتراک</Link>{account.user.role === "org_admin" ? <Link className="btn-ghost" to="/account-settings">تنظیمات حساب</Link> : null}</nav> : null}
        </>
      ) : null}
    </div>
  );
}
