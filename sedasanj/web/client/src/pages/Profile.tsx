import { useEffect, useState } from "react";
import { request } from "../api";
import { ROLE_LABELS } from "../auth";
import { ErrorBox, Loading } from "../components/Widgets";
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
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-[#4B6E48]">پروفایل من</h1>
        <p className="mt-1 text-sm text-slate-500">اطلاعاتی که دستیار برای شناخت و ارتباط بهتر با شما استفاده می‌کند.</p>
      </div>
      <ErrorBox message={error} />
      {account ? (
        <form className="card space-y-5" onSubmit={submit}>
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
          <div className="grid gap-4 border-y border-[#D8D3B9] py-4 text-sm md:grid-cols-2">
            <div><span className="text-slate-500">سازمان</span><strong className="mt-1 block text-[#4B6E48]">{account.tenant.name}</strong></div>
            <div><span className="text-slate-500">نقش</span><strong className="mt-1 block text-[#4B6E48]">{ROLE_LABELS[account.user.role] || account.user.role}</strong></div>
          </div>
          <label>
            <span className="label">درباره من و شیوه ارتباط دلخواه</span>
            <textarea
              className="input min-h-40 resize-y leading-7"
              value={form.profile_context}
              onChange={(event) => setForm({ ...form, profile_context: event.target.value })}
              maxLength={2000}
              placeholder="درباره مسئولیت‌ها، حوزه کاری، علایق حرفه‌ای و لحنی که ترجیح می‌دهید دستیار با شما صحبت کند بنویسید."
            />
            <span className="mt-1 block text-left text-xs text-slate-400" dir="ltr">{form.profile_context.length} / 2000</span>
          </label>
          {account.user.role === "operator" ? <p className="text-xs text-slate-500">برای اپراتور ثبت حداقل یکی از شماره موبایل یا شماره داخلی الزامی است.</p> : null}
          <div className="flex items-center gap-3">
            <button className="btn" disabled={saving}>{saving ? "در حال ذخیره…" : "ذخیره پروفایل"}</button>
            {saved ? <span className="text-sm font-medium text-[#4B6E48]">پروفایل ذخیره شد.</span> : null}
          </div>
        </form>
      ) : null}
    </div>
  );
}
