import { Icon } from "../components/SiteIcon";
import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { request } from "../api";
import { useAuth } from "../auth";
import { BrandLogo } from "../components/BrandLogo";
import PhoneAuth from "../components/PhoneAuth";
import { freePbxModuleConfig, pythonAgentConfig } from "../agentConfig";
import { srcSetFor } from "../lib/imageSources";
import voipIntegrationArtwork from "../assets/quick-demo-voip-integration.webp";
import type { ApiKeyCreated } from "../types";
import "../components/quick-demo.css";

interface DemoSession { session_id: string; token: string; expires_at: string; max_duration_seconds: number }
const storageKey = (user: string) => `sedasanj.quick-demo.${user}`;
function restore(user: string): DemoSession | null {
  try { const value = JSON.parse(sessionStorage.getItem(storageKey(user)) || "null") as DemoSession | null;
    return value && new Date(value.expires_at).getTime() > Date.now() ? value : null;
  } catch { return null; }
}

export default function QuickDemo() {
  const { session, acceptSession } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [demo, setDemo] = useState<DemoSession | null>(() => session ? restore(session.userId) : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [callId, setCallId] = useState("");
  const [voipKey, setVoipKey] = useState<ApiKeyCreated | null>(null);
  const [voipKeyBusy, setVoipKeyBusy] = useState(false);
  const [voipKeyError, setVoipKeyError] = useState("");
  const [now, setNow] = useState(Date.now());
  const initiated = useRef(false);
  const expired = !!demo && new Date(demo.expires_at).getTime() <= now;
  const sessionId = demo?.session_id || params.get("session");
  const activePath = ["mobile", "voip", "same"].includes(params.get("path") || "") ? params.get("path") as "mobile" | "voip" | "same" : null;
  const showContent = params.get("stage") === "content" && activePath !== null;
  const link = demo ? `${window.location.origin}/demo/record#${demo.token}` : "";
  const method = params.get("device") === "same" ? "same" : "qr";
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  useEffect(() => {
    if (session && showContent && (activePath === "mobile" || activePath === "same") && (!demo || expired) && !initiated.current) { initiated.current = true; void create(); }
  }, [session, showContent, activePath, demo, sessionId]);
  useEffect(() => {
    if (session && showContent && activePath === "same" && demo && !expired) navigate(`/demo/record#${demo.token}`, { replace: true });
  }, [session, showContent, activePath, demo, expired, navigate]);
  useEffect(() => {
    if (!session || !showContent || activePath !== "mobile" || !sessionId || callId) return;
    let cancelled = false;
    async function poll() {
      try {
        const result = await request<{ call_id: string | null; call_deleted: boolean }>(`/v1/quick-demo/sessions/${sessionId}`);
        if (cancelled) return;
        if (result.call_deleted) {
          sessionStorage.removeItem(storageKey(session!.userId));
          setDemo(null); setError(""); setCallId(""); initiated.current = false;
          return;
        }
        if (result.call_id) {
          sessionStorage.removeItem(storageKey(session!.userId));
          setDemo(null);
          setParams((current) => { const next = new URLSearchParams(current); next.delete("session"); next.delete("path"); next.set("stage", "choice"); return next; }, { replace: true });
          setCallId(result.call_id);
        }
      } catch (reason) { if (!cancelled) setError((reason as Error).message); }
    }
    void poll(); const timer = expired ? undefined : setInterval(() => void poll(), 1000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [session, showContent, activePath, sessionId, callId, expired, method, setParams]);
  useEffect(() => {
    if (callId) navigate(`/calls/${callId}`, { replace: true });
  }, [callId, navigate]);
  async function create() {
    setBusy(true); setError(""); setCallId("");
    try {
      const value = await request<DemoSession>("/v1/quick-demo/sessions", { method: "POST", retry: false });
      setDemo(value); sessionStorage.setItem(storageKey(session!.userId), JSON.stringify(value));
      setParams((current) => { const next = new URLSearchParams(current); next.set("stage", "content"); next.set("path", activePath || "mobile"); next.set("device", method); next.set("session", value.session_id); return next; }, { replace: true });
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }
  async function createVoipKey() {
    if (voipKey || voipKeyBusy) return;
    setVoipKeyBusy(true);
    setVoipKeyError("");
    try {
      const key = await request<ApiKeyCreated>("/v1/auth/api-keys", {
        method: "POST",
        body: { label: "تست VoIP صداسنج", archive_format: "gzip", archive_password: null },
      });
      setVoipKey(key);
    } catch (reason) {
      setVoipKeyError((reason as Error).message);
    } finally {
      setVoipKeyBusy(false);
    }
  }
  function downloadConfig(filename: string, contents: string) {
    const type = filename.endsWith(".toml") ? "text/plain;charset=utf-8" : "application/json;charset=utf-8";
    const url = URL.createObjectURL(new Blob([contents], { type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  async function copyText(value: string) {
    await navigator.clipboard.writeText(value);
  }
  const pageClass = "quick-demo-auth-page relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 px-4 py-8";
  const pageStyle = { backgroundImage: "radial-gradient(circle, rgb(75 110 72 / 0.18) 0 1px, transparent 1.15px)", backgroundPosition: "0 0", backgroundSize: "8px 8px" } as const;
  if (!session) return <main className={pageClass} dir="rtl" style={pageStyle}>
    <div className="relative w-full max-w-md">
      <div className="mb-5 flex w-full justify-center"><Link to="/" aria-label="صفحه اصلی"><BrandLogo animated className="block w-48 sm:w-56" title="صدا سنج" /></Link></div>
      <section className="relative w-full overflow-hidden border border-brand-200 bg-white/90 p-4 shadow-2xl shadow-brand-950/10 backdrop-blur-sm sm:p-6"><div className="mx-auto max-w-sm"><PhoneAuth onSuccess={(pair) => { acceptSession(pair); setParams({ step: "connect" }, { replace: true }); }}/></div></section>
    </div>
  </main>;

  function selectPath(path: "mobile" | "voip" | "same") {
    setParams((current) => { const next = new URLSearchParams(current); next.set("stage", "content"); next.set("path", path); next.delete("tab"); return next; }, { replace: true });
  }
  function goBack() {
    setParams((current) => { const next = new URLSearchParams(current); next.set("stage", "choice"); return next; }, { replace: true });
  }

  return <main className={pageClass} dir="rtl" style={pageStyle}><div className="relative w-full max-w-lg">
    <div className="mb-5 flex w-full justify-center"><Link to="/" aria-label="صفحه اصلی"><BrandLogo animated className="block w-48 sm:w-56" title="صدا سنج" /></Link></div>
    <section className="quick-demo-qr-card relative w-full overflow-hidden border border-brand-200 bg-white/90 p-5 shadow-2xl shadow-brand-950/10 backdrop-blur-sm sm:p-7">
      <header className="quick-demo-choice-heading">
        {showContent ? <><button type="button" className="quick-demo-back" onClick={goBack} aria-label="بازگشت به انتخاب مسیر"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 12H5m7 7-7-7 7-7"/></svg></button><div><h1>{activePath === "mobile" ? "تست موبایل" : "نصب VoIP"}</h1></div></> : <div><h1>آماده‌اید؟</h1><p>از کدام مسیر تست کنیم؟</p></div>}
      </header>
      {!showContent && <div className="quick-demo-path-options" role="radiogroup" aria-label="مسیر تست">
        <label className="quick-demo-path-option"><input type="radio" name="demo-path" checked={activePath === "mobile"} onChange={() => selectPath("mobile")}/><span className="quick-demo-path-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="6" y="2.5" width="12" height="19" rx="2.2"/><path d="M10 5h4M11 18.5h2"/></svg></span><span><strong>تست موبایل</strong><small>ضبط پیام با گوشی و اسکن QR</small></span></label>
        <label className="quick-demo-path-option"><input type="radio" name="demo-path" checked={activePath === "same"} onChange={() => selectPath("same")}/><span className="quick-demo-path-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="13" rx="1.5"/><path d="M8 21h8m-4-5v5m-2-12a2 2 0 0 1 4 0v2a2 2 0 0 1-4 0zm2-3V6m-3 4v1a3 3 0 0 0 6 0v-1"/></svg></span><span><strong>تست با همین دیوایس</strong><small>مطمئن شوید که این دیوایس میکروفون متصل و فعال دارد</small></span></label>
        <label className="quick-demo-path-option"><input type="radio" name="demo-path" checked={activePath === "voip"} onChange={() => selectPath("voip")}/><span className="quick-demo-path-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 4.5a2 2 0 0 1 2-2h2.2a1.5 1.5 0 0 1 1.46 1.15l.7 2.8a1.5 1.5 0 0 1-.75 1.67l-1.55.89a13.1 13.1 0 0 0 5.93 5.93l.89-1.55a1.5 1.5 0 0 1 1.67-.75l2.8.7a1.5 1.5 0 0 1 1.15 1.46V17a2 2 0 0 1-2 2h-1C10.5 19 5 13.5 5 6.5z"/><path d="M14 4a6 6 0 0 1 6 6M14 7a3 3 0 0 1 3 3"/></svg></span><span><strong>نصب در VOIP</strong><small>اتصال به صداسنج از طریق سامانه تلفنی</small></span></label>
      </div>}
      {showContent && <div className="quick-demo-content-stage">
        {activePath === "mobile" && <div id="quick-demo-panel" className="mx-auto max-w-sm text-center">
      {error && !demo && <p className="demo-error" role="alert">{error}</p>}
      {demo && !expired && <div className="quick-demo-qr-content">
        <div className="demo-qr quick-demo-entry-qr"><div className="quick-demo-qr-frame"><QRCodeSVG value={link} size={244} level="H" marginSize={3} fgColor="#294c2b" bgColor="#ffffff" title="کد ورود به تست موبایل"/></div></div>
        <p className="quick-demo-qr-guide">دوربین گوشی را باز کنید و کد را اسکن کنید</p>
      </div>}
      {(!demo || expired) && busy && <span className="demo-spinner quick-demo-qr-spinner" role="status" aria-label="در حال ساخت QR"/>}
      {error && <p className="demo-error" role="alert">{error}</p>}
        </div>}
        {activePath === "voip" && <div className="quick-demo-voip-content">
          <img className="quick-demo-voip-artwork" src={voipIntegrationArtwork} srcSet={srcSetFor(voipIntegrationArtwork)} sizes="(max-width: 528px) calc(100vw - 48px), 480px" width={1000} height={667} alt="اتصال FreePBX و Issabel به صداسنج" decoding="async" />
          {!voipKey ? <div className="grid justify-items-center gap-3 py-2 text-center">
            <p className="text-sm leading-7 text-slate-600">کلید API و فایل تنظیمات اتصال VoIP را دریافت کنید.</p>
            {voipKeyError ? <p className="demo-error" role="alert">{voipKeyError}</p> : null}
            <div className="quick-demo-voip-actions"><button type="button" className="btn" onClick={() => void createVoipKey()} disabled={voipKeyBusy}>{voipKeyBusy ? "در حال ساخت…" : <><Icon name="key" size={18}/>ساخت کلید API</>}</button><a className="btn-ghost" href="https://github.com/aminazadi/Sedasanj-Module.git" target="_blank" rel="noreferrer"><Icon name="download" size={18}/>دانلود ماژول</a></div>
          </div> : <div className="space-y-4 text-sm">
            <div className="border border-emerald-200 bg-emerald-50 p-4">
              <h2 className="font-bold text-emerald-900">کلید API ساخته شد</h2>
              <p className="mt-1 text-emerald-800">این کلید فقط همین‌بار نمایش داده می‌شود. آن را در جای امن نگه دارید.</p>
              <div className="mt-3 flex flex-wrap items-center gap-2" dir="ltr"><code className="min-w-0 flex-1 break-all bg-white p-3">{voipKey.secret}</code><button type="button" className="btn-ghost" onClick={() => void copyText(voipKey.secret)}><Icon name="copy" size={18}/>کپی کلید</button></div>
              <p className="mt-2 text-xs text-slate-600">پیشوند: <bdi dir="ltr">{voipKey.key_prefix}</bdi> · فرمت ارسال: GZIP</p>
            </div>
            <div className="border border-slate-200 p-4">
              <h3 className="font-bold">فایل‌های تنظیمات اتصال</h3>
              <p className="mt-1 text-xs leading-6 text-slate-600">یکی از فایل‌ها را متناسب با روش نصب دانلود و در سامانه تلفنی وارد کنید.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" className="btn" onClick={() => downloadConfig("sedasanj-freepbx-config.json", freePbxModuleConfig(window.location.origin, voipKey.id, voipKey.key_prefix, voipKey.secret, voipKey.archive_format, ""))}><Icon name="download" size={18}/>دانلود تنظیمات FreePBX</button>
                <button type="button" className="btn-ghost" onClick={() => downloadConfig("cbi-agent.toml", pythonAgentConfig(window.location.origin, voipKey.secret, voipKey.archive_format, ""))}><Icon name="download" size={18}/>دانلود تنظیمات Python Agent</button>
                <button type="button" className="btn-ghost" onClick={() => void copyText(freePbxModuleConfig(window.location.origin, voipKey.id, voipKey.key_prefix, voipKey.secret, voipKey.archive_format, ""))}><Icon name="copy" size={18}/>کپی تنظیمات FreePBX</button>
                <a className="btn-ghost" href="https://github.com/aminazadi/Sedasanj-Module.git" target="_blank" rel="noreferrer"><Icon name="download" size={18}/>دانلود ماژول</a>
              </div>
            </div>
          </div>}
        </div>}
        {activePath === "same" && <div className="quick-demo-same-device" role="status"><span className="demo-spinner"/><p>در حال آماده‌سازی تست با میکروفون همین دستگاه…</p></div>}
      </div>}
    </section>
  </div></main>;
}
