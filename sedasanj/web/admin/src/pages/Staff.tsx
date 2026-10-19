import { useEffect, useState } from "react";
import { ApiError, fmt, request } from "../api";
import { useAuth } from "../auth";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Page } from "../types";

interface StaffRow { id: string; email: string; role: string; two_factor_enabled: boolean; disabled_at: string | null; created_at: string }
interface ResetTarget { id: string; email: string }

function apiMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : "عملیات ناموفق بود. دوباره تلاش کنید.";
  if (error.status === 422) return "رمز جدید باید حداقل ۸ نویسه داشته باشد.";
  if (error.status === 401) return "رمز فعلی یا کد دومرحله‌ای واردشده معتبر نیست.";
  if (error.status === 404) return "کاربر ادمین موردنظر پیدا نشد.";
  return error.message || "عملیات ناموفق بود. دوباره تلاش کنید.";
}

export default function Staff() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const { session } = useAuth();
  const [page, setPage] = useState<Page<StaffRow> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [resetTarget, setResetTarget] = useState<ResetTarget | null>(null);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetForm, setResetForm] = useState({ current_password: "", totp_code: "", password: "", confirm_password: "" });
  const [form, setForm] = useState({ email: "", password: "", role: "support", current_password: "", totp_code: "" });

  async function load() {
    try {
      setPage(await request<Page<StaffRow>>(`/v1/admin/staff?offset=${offset}&limit=${limit}`));
      setError(null);
    } catch (reason) {
      setError(apiMessage(reason));
    }
  }

  useEffect(() => { void load(); }, [offset]);

  function closeReset() {
    if (resetBusy) return;
    setResetTarget(null);
    setResetError(null);
    setResetForm({ current_password: "", totp_code: "", password: "", confirm_password: "" });
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await request("/v1/admin/staff", { method: "POST", body: { ...form, totp_code: form.totp_code || null } });
      setForm({ ...form, email: "", password: "" });
      setNotice("کاربر ادمین با موفقیت ایجاد شد.");
      await load();
    } catch (reason) {
      setError(apiMessage(reason));
    }
  }

  async function toggle(item: StaffRow) {
    const password = window.prompt("رمز فعلی خودتان را وارد کنید");
    if (!password) return;
    const code = window.prompt("کد دومرحله‌ای، در صورت فعال بودن");
    setError(null);
    try {
      await request(`/v1/admin/staff/${item.id}/${item.disabled_at ? "activate" : "disable"}`, { method: "POST", body: { current_password: password, totp_code: code || null } });
      await load();
    } catch (reason) {
      setError(apiMessage(reason));
    }
  }

  async function resetPassword(event: React.FormEvent) {
    event.preventDefault();
    if (!resetTarget) return;
    if (resetForm.password.length < 8) {
      setResetError("رمز جدید باید حداقل ۸ نویسه داشته باشد.");
      return;
    }
    if (resetForm.password !== resetForm.confirm_password) {
      setResetError("تکرار رمز جدید با رمز واردشده یکسان نیست.");
      return;
    }
    setResetBusy(true);
    setResetError(null);
    try {
      await request(`/v1/admin/staff/${resetTarget.id}/reset-password`, {
        method: "POST",
        body: { current_password: resetForm.current_password, totp_code: resetForm.totp_code || null, password: resetForm.password },
      });
      setNotice(`رمز عبور ${resetTarget.email} با موفقیت بازنشانی شد.`);
      closeReset();
      await load();
    } catch (reason) {
      setResetError(apiMessage(reason));
    } finally {
      setResetBusy(false);
    }
  }

  async function resetTotp(item: StaffRow) {
    const current = window.prompt("رمز فعلی خودتان را وارد کنید");
    if (!current) return;
    const code = window.prompt("کد دومرحله‌ای، در صورت فعال بودن");
    setError(null);
    try {
      await request(`/v1/admin/staff/${item.id}/reset-totp`, { method: "POST", body: { current_password: current, totp_code: code || null } });
      setNotice(`ورود دومرحله‌ای ${item.email} حذف شد.`);
      await load();
    } catch (reason) {
      setError(apiMessage(reason));
    }
  }

  const rows = page?.items ?? null;
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">کاربران ادمین</h1>
        <p className="mt-1 text-sm text-slate-500">همه نقش‌های staff دسترسی کامل دارند؛ عملیات حساس نیازمند احراز مجدد است.</p>
      </header>
      <ErrorBox message={error} />
      {notice ? <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">{notice}</div> : null}

      <form className="card grid gap-3 md:grid-cols-3" onSubmit={create}>
        <input className="input" type="email" dir="ltr" placeholder="ایمیل" value={form.email} onChange={event => setForm({ ...form, email: event.target.value })} required />
        <input className="input" type="password" dir="ltr" placeholder="رمز کاربر جدید" value={form.password} onChange={event => setForm({ ...form, password: event.target.value })} minLength={8} required />
        <select className="input" value={form.role} onChange={event => setForm({ ...form, role: event.target.value })}><option value="support">پشتیبانی</option><option value="super_admin">مدیر کل</option></select>
        <input className="input" type="password" dir="ltr" placeholder="رمز فعلی شما" value={form.current_password} onChange={event => setForm({ ...form, current_password: event.target.value })} required />
        <input className="input" dir="ltr" inputMode="numeric" placeholder="کد دومرحله‌ای شما" value={form.totp_code} onChange={event => setForm({ ...form, totp_code: fmt.latinDigits(event.target.value) })} />
        <button className="btn">ایجاد کاربر</button>
      </form>

      <div className="card overflow-x-auto">
        {!rows ? <Loading /> : rows.length === 0 ? <Empty /> : (
          <table className="table">
            <thead><tr><th>ایمیل</th><th>نقش</th><th>ورود دومرحله‌ای</th><th>وضعیت</th><th>ایجاد</th><th>عملیات</th></tr></thead>
            <tbody>{rows.map(item => (
              <tr key={item.id}>
                <td dir="ltr">{item.email}</td><td>{item.role}</td><td>{item.two_factor_enabled ? "فعال" : "غیرفعال"}</td><td>{item.disabled_at ? "غیرفعال" : "فعال"}</td><td>{fmt.date(item.created_at)}</td>
                <td><div className="flex flex-wrap items-center gap-2">
                  {item.id !== session?.staffId ? <button className="btn-ghost text-xs" onClick={() => void toggle(item)}>{item.disabled_at ? "فعال‌سازی" : "غیرفعال‌سازی"}</button> : <span className="text-xs text-slate-400">حساب شما</span>}
                  <button className="btn-ghost text-xs" onClick={() => { setNotice(null); setResetError(null); setResetTarget({ id: item.id, email: item.email }); }}>بازنشانی رمز</button>
                  {item.two_factor_enabled ? <button className="btn-ghost text-xs text-rose-700" onClick={() => void resetTotp(item)}>حذف ورود دومرحله‌ای</button> : null}
                </div></td>
              </tr>
            ))}</tbody>
          </table>
        )}
        {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
      </div>

      {resetTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-950/55 p-4 backdrop-blur-sm" onMouseDown={event => { if (event.target === event.currentTarget) closeReset(); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="reset-password-title" className="my-auto w-full max-w-lg overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-950/25">
            <div className="border-b border-slate-100 bg-gradient-to-l from-emerald-50 to-white px-6 py-5">
              <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-100 text-xl text-emerald-800" aria-hidden="true">♧</div>
              <h2 id="reset-password-title" className="text-xl font-bold text-slate-900">بازنشانی رمز عبور</h2>
              <p className="mt-1 text-sm text-slate-600">برای حساب <span className="font-semibold text-slate-800" dir="ltr">{resetTarget.email}</span></p>
            </div>
            <form className="space-y-4 px-6 py-5" onSubmit={resetPassword}>
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">پس از ثبت رمز جدید، نشست‌های فعال این کاربر باطل می‌شوند و باید دوباره وارد شود.</div>
              <ErrorBox message={resetError} />
              <label className="block"><span className="mb-1.5 block text-sm font-medium text-slate-700">رمز فعلی شما</span><input className="input" type="password" dir="ltr" autoComplete="current-password" value={resetForm.current_password} onChange={event => setResetForm({ ...resetForm, current_password: event.target.value })} required /></label>
              <label className="block"><span className="mb-1.5 block text-sm font-medium text-slate-700">کد دومرحله‌ای شما <span className="font-normal text-slate-400">(در صورت فعال بودن)</span></span><input className="input" type="text" inputMode="numeric" dir="ltr" autoComplete="one-time-code" value={resetForm.totp_code} onChange={event => setResetForm({ ...resetForm, totp_code: fmt.latinDigits(event.target.value).replace(/\D/g, "").slice(0, 6) })} /></label>
              <label className="block"><span className="mb-1.5 block text-sm font-medium text-slate-700">رمز جدید کاربر</span><input className="input" type="password" dir="ltr" autoComplete="new-password" minLength={8} value={resetForm.password} onChange={event => setResetForm({ ...resetForm, password: event.target.value })} required /><span className="mt-1 block text-xs text-slate-500">حداقل ۸ نویسه</span></label>
              <label className="block"><span className="mb-1.5 block text-sm font-medium text-slate-700">تکرار رمز جدید</span><input className="input" type="password" dir="ltr" autoComplete="new-password" minLength={8} value={resetForm.confirm_password} onChange={event => setResetForm({ ...resetForm, confirm_password: event.target.value })} required /></label>
              <div className="flex flex-col-reverse gap-2 border-t border-slate-100 pt-4 sm:flex-row sm:justify-end">
                <button className="btn-ghost justify-center" type="button" disabled={resetBusy} onClick={closeReset}>انصراف</button>
                <button className="btn justify-center" type="submit" disabled={resetBusy}>{resetBusy ? "در حال ذخیره…" : "ثبت رمز جدید"}</button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </div>
  );
}
