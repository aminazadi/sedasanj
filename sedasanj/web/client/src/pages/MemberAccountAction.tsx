import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { request } from "../api";

export default function MemberAccountAction() {
  const [params] = useState(() => new URLSearchParams(window.location.hash.slice(1)));
  const emailToken = params.get("email");
  const token = emailToken ?? params.get("password");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [complete, setComplete] = useState(false);

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || busy) return;
    setBusy(true);
    setError("");
    try {
      await request<void>(emailToken
        ? "/v1/auth/member-email-change/confirm"
        : "/v1/auth/member-password-reset/confirm", {
        method: "POST",
        body: emailToken ? { token } : { token, password },
      });
      window.history.replaceState(window.history.state, "", window.location.pathname);
      setPassword("");
      setComplete(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <main className="mx-auto max-w-md p-6" dir="rtl">
    <h1>{emailToken ? "تأیید ایمیل جدید" : "بازنشانی گذرواژه"}</h1>
    {complete ? <p role="status">تغییر ذخیره شد. <Link to="/login">ورود به صداسنج</Link></p>
      : token ? <form onSubmit={(event) => void confirm(event)}>
        {emailToken ? <p>برای ثبت ایمیل جدید به عنوان شناسهٔ ورود، آن را تأیید کنید.</p> : <label>
          <span>گذرواژهٔ جدید</span>
          <input type="password" dir="ltr" autoComplete="new-password" required minLength={8}
            maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>}
        {error ? <p role="alert">{error}</p> : null}
        <button className="btn" disabled={busy}>{emailToken ? "تأیید ایمیل" : "ذخیرهٔ گذرواژه"}</button>
      </form> : <p role="alert">از مدیر سازمان بخواهید پیوند تازه‌ای بفرستد.</p>}
  </main>;
}
