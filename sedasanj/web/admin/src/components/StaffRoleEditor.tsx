import { useState } from "react";
import { ApiError, fmt, request } from "../api";
import { ErrorBox } from "./Widgets";

export interface StaffRoleTarget { id: string; email: string; role: string }

export default function StaffRoleEditor({ target, onClose, onSaved }: {
  target: StaffRoleTarget;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [role, setRole] = useState(target.role);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (busy || role === target.role) return;
    setBusy(true);
    setError(null);
    try {
      await request(`/v1/admin/staff/${encodeURIComponent(target.id)}/role`, {
        method: "PATCH",
        body: { role, current_password: password, totp_code: code || null },
      });
      await onSaved();
      onClose();
    } catch (reason) {
      const messages: Record<string, string> = {
        unauthorized: "رمز فعلی یا کد دومرحله‌ای معتبر نیست؛ اطلاعات خودتان را دوباره وارد کنید.",
        forbidden: "تغییر نقش فقط برای مدیر کل مجاز است؛ از مدیر کل بخواهید اقدام کند.",
        not_found: "کاربر پیدا نشد؛ پنجره را ببندید و فهرست کاربران را تازه کنید.",
        invalid_request: "نقش و کد دومرحله‌ای را بررسی کنید؛ تغییر نقش حساب خودتان مجاز نیست.",
      };
      setError(reason instanceof ApiError && messages[reason.code]
        ? messages[reason.code] : "ذخیرهٔ نقش ممکن نشد؛ دوباره تلاش کنید.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-950/55 p-4"
      onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="staff-role-title"
        className="my-auto w-full max-w-lg border border-slate-200 bg-white p-6 shadow-xl">
        <h2 id="staff-role-title" className="text-xl font-bold">ویرایش سطح دسترسی</h2>
        <p className="my-3" dir="ltr">{target.email}</p>
        <form className="space-y-4" onSubmit={event => void save(event)}>
          <ErrorBox message={error} />
          <label className="block"><span className="mb-1 block">نقش</span>
            <select className="input" value={role} disabled={busy} onChange={event => setRole(event.target.value)}>
              <option value="support">پشتیبانی</option><option value="super_admin">مدیر کل</option>
            </select>
          </label>
          <p className="text-sm text-slate-600">مدیر کل تنظیمات و کاربران سامانه را مدیریت می‌کند. پشتیبانی به عملیات روزمرهٔ سازمان‌ها دسترسی دارد. دسترسی جدید از درخواست بعدی کاربر اعمال می‌شود.</p>
          <label className="block"><span className="mb-1 block">رمز فعلی شما</span>
            <input className="input" type="password" dir="ltr" autoComplete="current-password"
              required value={password} disabled={busy} onChange={event => setPassword(event.target.value)} />
          </label>
          <label className="block"><span className="mb-1 block">کد دومرحله‌ای شما (در صورت فعال بودن)</span>
            <input className="input" dir="ltr" inputMode="numeric" autoComplete="one-time-code"
              maxLength={6} value={code} disabled={busy}
              onChange={event => setCode(fmt.latinDigits(event.target.value).replace(/\D/g, ""))} />
          </label>
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" type="button" disabled={busy} onClick={onClose}>انصراف</button>
            <button className="btn" type="submit" disabled={busy || role === target.role}>{busy ? "در حال ذخیره…" : "ذخیره"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}
