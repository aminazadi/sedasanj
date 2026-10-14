import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { ROLE_LABELS } from "../auth";
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

export default function Profile() {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [form, setForm] = useState<ProfileForm>(EMPTY_PROFILE);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

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

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const user = await request<User>("/v1/auth/me", {
        method: "PATCH",
        body: {
          display_name: form.display_name.trim(),
          mobile_number: form.mobile_number.trim() || null,
          extension: form.extension.trim() || null,
          profile_context: form.profile_context.trim() || null,
        },
      });
      setAccount((current) => current ? { ...current, user } : current);
      setSaved(true);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!account && !error) return <Loading />;

  return (
    <div className="mx-auto max-w-5xl space-y-5" dir="rtl">
      <PageHeader title="پروفایل من" description="مشخصات فردی، راه‌های تماس و امنیت ورود شما" />
      <ErrorBox message={error} />
      {account ? (
        <>
        <section className="card grid gap-5 md:grid-cols-[auto_minmax(0,1fr)] md:items-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#E7ECDD] text-2xl font-bold text-[#4B6E48]" aria-hidden="true">{(account.user.display_name || account.user.email).slice(0, 1)}</div>
          <div className="min-w-0">
            <h2 className="truncate text-xl font-bold text-slate-800">{account.user.display_name || account.user.email}</h2>
            <p className="mt-1 break-all text-sm text-slate-500" dir="ltr">{account.user.email}</p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-[#E7ECDD] px-3 py-1 text-[#4B6E48]">{ROLE_LABELS[account.user.role] || account.user.role}</span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">{account.tenant.name}</span>
              <span className="rounded-full bg-slate-100 px-3 py-1 text-slate-700">عضویت از {fmt.date(account.user.created_at)}</span>
            </div>
          </div>
        </section>
        <form className="card space-y-5" onSubmit={submit}>
          <div><h2 className="font-bold text-slate-800">اطلاعات فردی</h2><p className="mt-1 text-sm text-slate-500">این اطلاعات برای شناسایی شما و شخصی‌سازی دستیار استفاده می‌شود.</p></div>
          <div className="grid gap-4 md:grid-cols-2">
            <label>
              <span className="label">نام و نام خانوادگی</span>
              <input className="input" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} minLength={2} maxLength={120} autoComplete="name" required />
            </label>
            <label>
              <span className="label">ایمیل</span>
              <input className="input bg-slate-50" value={account.user.email} dir="ltr" disabled />
            </label>
            <label>
              <span className="label">شماره موبایل</span>
              <input className="input" value={form.mobile_number} onChange={(event) => setForm({ ...form, mobile_number: event.target.value })} dir="ltr" inputMode="tel" autoComplete="tel" />
            </label>
            <label>
              <span className="label">شماره داخلی</span>
              <input className="input" value={form.extension} onChange={(event) => setForm({ ...form, extension: event.target.value })} dir="ltr" inputMode="numeric" />
            </label>
          </div>
          <label className="block border-t border-[#D8D3B9] pt-5">
            <span className="label">درباره من و شیوه ارتباط دلخواه</span>
            <textarea
              className="input min-h-40 resize-y leading-7"
              value={form.profile_context}
              onChange={(event) => setForm({ ...form, profile_context: event.target.value })}
              maxLength={2000}
              placeholder="درباره مسئولیت‌ها، حوزه کاری، علایق حرفه‌ای و لحنی که ترجیح می‌دهید دستیار با شما صحبت کند بنویسید."
            />
            <span className="mt-1 block text-left text-xs text-slate-400">{fmt.int(form.profile_context.length)} / {fmt.int(2000)}</span>
          </label>
          {account.user.role === "operator" ? <p className="text-xs text-slate-500">برای اپراتور ثبت حداقل یکی از شماره موبایل یا شماره داخلی الزامی است.</p> : null}
          <div className="flex items-center gap-3">
            <button className="btn" disabled={saving}>{saving ? "در حال ذخیره…" : "ذخیره پروفایل"}</button>
            {saved ? <span className="text-sm font-medium text-[#4B6E48]">پروفایل ذخیره شد.</span> : null}
          </div>
        </form>
        {account.user.role === "org_admin" ? <TwoFactorSettings /> : null}
        {account.user.role !== "operator" ? <nav className="card flex flex-wrap items-center gap-3" aria-label="بخش‌های مرتبط حساب"><Link className="btn-ghost" to="/account">اعتبار و اشتراک</Link>{account.user.role === "org_admin" ? <Link className="btn-ghost" to="/account-settings">تنظیمات حساب</Link> : null}</nav> : null}
        </>
      ) : null}
    </div>
  );
}
