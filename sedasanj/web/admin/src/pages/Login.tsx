import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { ErrorBox } from "../components/Widgets";
import logo from "../assets/logo-small-fa.webp";
import pattern from "../assets/pattern.webp";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "ورود ناموفق بود");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main
      className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-100 px-4 py-8"
      style={{ backgroundImage: `url(${pattern})`, backgroundPosition: "center", backgroundSize: "cover" }}
    >
      <div className="absolute inset-0 bg-slate-950/10" />
      <form
        onSubmit={submit}
        className="relative w-full max-w-md rounded-3xl border border-white/80 bg-white/95 p-7 shadow-2xl shadow-slate-950/10 backdrop-blur-sm sm:p-10"
      >
        <img className="mb-8 h-12 w-auto" src={logo} alt="صدا سنج" />
        <div className="mb-8 border-r-4 border-brand-500 pr-3">
          <h1 className="text-2xl font-bold text-slate-900">ورود به پنل</h1>
        </div>
        <ErrorBox message={error} />
        <label className="label font-medium text-slate-700" htmlFor="email">
          ایمیل
        </label>
        <input
          id="email"
          className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white"
          type="text"
          autoComplete="username"
          dir="ltr"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <label className="label font-medium text-slate-700" htmlFor="password">
          گذرواژه
        </label>
        <input
          id="password"
          className="input mb-4 border-slate-200 bg-slate-50 py-2.5 focus:bg-white"
          type="password"
          dir="ltr"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        <button className="btn w-full py-3 font-bold shadow-lg shadow-brand-500/25" disabled={busy}>
          {busy ? "…" : "ورود"}
        </button>
      </form>
    </main>
  );
}
