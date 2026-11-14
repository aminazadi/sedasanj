import { cssImageSetFor } from "../lib/imageSources";
import { useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth";
import PhoneAuth from "./PhoneAuth";
import phoneAuthDialogImage from "../assets/phone-auth-dialog.webp";
import phoneAuthOtpImage from "../assets/phone-auth-otp.webp";
import phoneAuthOrganizationImage from "../assets/phone-auth-organization.webp";

export default function QuickDemoEntry() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { acceptSession, session } = useAuth();
  const dialog = useRef<HTMLDialogElement>(null);
  const open = params.get("quickDemo") === "1";
  useEffect(() => {
    if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current?.close();
  }, [open]);
  function close() {
    setParams((current) => { const next = new URLSearchParams(current); next.delete("quickDemo"); next.delete("authStep"); return next; }, { replace: true });
  }
  function start() {
    if (session) { navigate("/quick-demo?step=connect"); return; }
    setParams((current) => { const next = new URLSearchParams(current); next.set("quickDemo", "1"); return next; });
  }
  return <>
    <section className="site-section demo-landing-section" id="quick-test"><div className="site-container demo-landing-grid">
      <div className="demo-landing-copy"><h2>همین حالا امتحان کنید</h2><p>با موبایل وارد شوید، یک پیام صوتی ضبط کنید و نتیجه تحلیل را در پنل سازمان خود ببینید.</p><button className="site-button site-hero-demo" type="button" onClick={start}><svg className="hero-demo-border" aria-hidden="true" focusable="false"><rect className="hero-demo-border-track" pathLength="100"/><rect className="hero-demo-border-trail" pathLength="100"/></svg><span>تست صداسنج در کمتر از ۶۰ ثانیه</span></button></div>
    </div></section>
    <dialog className="demo-dialog" ref={dialog} aria-label="تست سریع صداسنج" onCancel={(e) => { e.preventDefault(); close(); }} onClick={(e) => { if (e.target === dialog.current) close(); }}>
      <button className="demo-dialog-close" aria-label="بستن" type="button" onClick={close}><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" focusable="false"><path d="m6 6 12 12M18 6 6 18" /></svg></button>
      {open && <PhoneAuth onSuccess={(pair) => { acceptSession(pair); navigate("/quick-demo?step=connect", { replace: true }); }} renderArtwork={(step) => <div className={`demo-dialog-artwork${step === "code" ? " is-otp" : step === "organization" ? " is-organization" : ""}`} style={{ backgroundImage: cssImageSetFor(step === "code" ? phoneAuthOtpImage : step === "organization" ? phoneAuthOrganizationImage : phoneAuthDialogImage) }} aria-hidden="true" />}/>}
    </dialog>
  </>;
}
