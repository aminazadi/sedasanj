import { useEffect, useState } from "react";
import { ApiError, request } from "../api";
import type { User } from "../types";
import FormDialog from "./FormDialog";

type UserFields = Pick<User, "display_name" | "mobile_number" | "extension">;

export default function EditOrganizationUser({ userId, onClose, onSaved }: {
  userId: string;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [user, setUser] = useState<User | null>(null);
  const [fields, setFields] = useState<UserFields | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [numberError, setNumberError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [accountNote, setAccountNote] = useState("");
  const [busy, setBusy] = useState(false);
  const path = `/v1/auth/users/${encodeURIComponent(userId)}`;

  useEffect(() => {
    let active = true;
    void request<User>(path).then((member) => {
      if (!active) return;
      setUser(member);
      setFields({
        display_name: member.display_name,
        mobile_number: member.mobile_number,
        extension: member.extension,
      });
    }).catch(() => {
      if (active) setError("بارگیری کاربر ممکن نشد. پنجره را ببندید و دوباره تلاش کنید.");
    });
    return () => { active = false; };
  }, [path]);

  function edit(field: keyof UserFields, value: string) {
    setFields((previous) => previous && { ...previous, [field]: value });
    if (field !== "display_name") setNumberError(null);
  }

  async function save() {
    if (!fields || !user || busy) return;
    const body = {
      display_name: fields.display_name?.trim() || null,
      mobile_number: fields.mobile_number?.trim() || null,
      extension: fields.extension?.trim() || null,
    };
    if (user.role === "operator" && !body.mobile_number && !body.extension) {
      setNumberError("برای اپراتور شماره موبایل یا شماره داخلی وارد کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    setNumberError(null);
    try {
      await request<User>(path, { method: "PATCH", body });
      await onSaved();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.code === "conflict_idempotency") {
        setNumberError("این موبایل یا داخلی به کاربر دیگری اختصاص دارد. شماره دیگری وارد کنید.");
      } else if (err instanceof ApiError && err.code === "invalid_request") {
        setNumberError("شماره موبایل یا داخلی معتبر وارد کنید.");
      } else {
        setError("ذخیرهٔ اطلاعات ممکن نشد. دوباره تلاش کنید.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function sendAccountLink(action: "email-change" | "password-reset") {
    if (busy) return;
    const email = newEmail.trim();
    if (action === "email-change" && !email) return;
    setBusy(true);
    setError(null);
    setAccountNote("");
    try {
      await request<void>(`${path}/${action}`, {
        method: "POST",
        ...(action === "email-change" ? { body: { email } } : {}),
      });
      setAccountNote(action === "email-change"
        ? "پیوند تأیید به ایمیل جدید ارسال شد."
        : "پیوند بازنشانی به ایمیل فعلی کاربر ارسال شد.");
      setNewEmail("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <FormDialog open title="ویرایش کاربر" submitLabel="ذخیره" busy={busy}
      error={error} submitDisabled={!fields} onClose={onClose} onSubmit={() => void save()}>
      {user && fields ? <>
        <p dir="ltr">{user.email}</p>
        <label>
          <span>نام نمایشی</span>
          <input value={fields.display_name ?? ""} maxLength={120} disabled={busy}
            onChange={(event) => edit("display_name", event.target.value)} />
        </label>
        <label>
          <span>شماره موبایل</span>
          <input value={fields.mobile_number ?? ""} dir="ltr" inputMode="tel" disabled={busy}
            aria-invalid={Boolean(numberError)} aria-describedby={numberError ? "edit-member-number-error" : undefined}
            onChange={(event) => edit("mobile_number", event.target.value)} />
        </label>
        <label>
          <span>شماره داخلی</span>
          <input value={fields.extension ?? ""} dir="ltr" inputMode="numeric" disabled={busy}
            aria-invalid={Boolean(numberError)} aria-describedby={numberError ? "edit-member-number-error" : undefined}
            onChange={(event) => edit("extension", event.target.value)} />
        </label>
        {numberError ? <p id="edit-member-number-error" className="demo-error" role="alert">{numberError}</p> : null}
        {user.role !== "org_admin" ? <>
        <label>
          <span>ایمیل جدید برای ارسال پیوند تأیید</span>
          <input dir="ltr" inputMode="email" value={newEmail} disabled={busy}
            onChange={(event) => setNewEmail(event.target.value)} />
        </label>
        <button type="button" className="btn-ghost" disabled={busy || !newEmail.trim()}
          onClick={() => void sendAccountLink("email-change")}>ارسال پیوند تأیید ایمیل</button>
        </> : null}
        <button type="button" className="btn-ghost" disabled={busy}
          onClick={() => void sendAccountLink("password-reset")}>ارسال پیوند بازنشانی گذرواژه</button>
        {accountNote ? <p role="status">{accountNote}</p> : null}
      </> : error ? null : <p role="status">در حال بارگیری اطلاعات کاربر…</p>}
    </FormDialog>
  );
}
