import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { request } from "../api";
import { Icon } from "./SiteIcon";
import logo from "../assets/sedasanj-refined-master.webp";
import "../pages/Landing.css";
import "../pages/PublicPages.css";

const DIGITS = "۰۱۲۳۴۵۶۷۸۹";

function MenuIcon({ close }: { close: boolean }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">{close ? <><path d="m6 6 12 12"/><path d="M18 6 6 18"/></> : <><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/></>}</svg>;
}

/** Header and footer shared by every public page except the landing page itself. */
export default function PublicPageFrame({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [siteContact, setSiteContact] = useState({ phone: "09399093062", trust_html: "" });
  const location = useLocation();

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [location.pathname]);
  useEffect(() => {
    request<{ phone: string; trust_html: string }>("/v1/site/contact-settings").then(setSiteContact).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuOpen]);

  const current = (path: string) => location.pathname === path ? "page" : undefined;
  return <div className="marketing-site public-site" dir="rtl">
    <header className="site-header"><div className="site-container site-nav">
      <Link to="/" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></Link>
      <nav id="site-navigation" className={menuOpen ? "site-links is-open" : "site-links"} aria-label="منوی اصلی">
        <Link to="/#features">امکانات</Link><Link to="/#pricing">تعرفه‌ها</Link><Link to="/help" aria-current={current("/help")}>مقالات</Link><Link to="/about" aria-current={current("/about")}>درباره ما</Link><Link to="/contact" aria-current={current("/contact")}>تماس با ما</Link>
      </nav>
      <div className="site-nav-actions"><Link className="site-button site-button-outline" to="/login"><Icon name="login" size={18}/>ورود به پنل</Link><button className="site-menu" type="button" aria-controls="site-navigation" aria-expanded={menuOpen} aria-label={menuOpen ? "بستن منو" : "باز کردن منو"} onClick={() => setMenuOpen(!menuOpen)}><MenuIcon close={menuOpen}/></button></div>
    </div></header>

    {children}

    <footer className="site-footer">
      <section className="site-footer-contact" aria-labelledby="site-footer-contact-title">
        <div className="site-container site-footer-contact-inner">
          <div><h2 id="site-footer-contact-title">با ما تماس بگیرید</h2><p>پذیرای صدای گرم شما خواهیم بود</p></div>
          <a className="site-footer-phone" href={`tel:${siteContact.phone}`} dir="rtl">{siteContact.phone.replace(/\d/g, (digit) => DIGITS[Number(digit)])}</a>
        </div>
      </section>
      <div className="site-container site-footer-main">
        <div className="site-footer-brand"><strong>درباره صداسنج</strong><Link to="/" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></Link><p>سامانه هوشمند تحلیل مکالمات فارسی</p></div>
        <nav className="site-footer-links" aria-label="لینک‌های پرکاربرد"><strong>لینک‌های پرکاربرد</strong><Link to="/#features">امکانات</Link><Link to="/#pricing">پلن‌ها</Link><Link to="/about">درباره ما</Link><Link to="/contact">تماس با ما</Link><Link to="/login">ورود به پنل</Link></nav>
        <nav className="site-footer-legal" aria-label="قوانین و حریم خصوصی"><Link to="/terms">قوانین استفاده</Link><Link to="/privacy">حریم خصوصی</Link><Link to="/cancellation">لغو اشتراک</Link></nav>
        <div className="site-footer-trust" aria-label="نمادهای اعتماد"><strong>نمادهای اعتماد</strong>{siteContact.trust_html ? <iframe className="site-footer-trust-frame" title="نمادهای اعتماد صداسنج" sandbox="allow-scripts" srcDoc={siteContact.trust_html}/> : <div className="site-footer-trust-slots"><span aria-hidden="true">جایگاه نماد</span><span aria-hidden="true">جایگاه نماد</span></div>}</div>
      </div>
      <div className="site-container site-footer-bottom"><small>© ۱۴۰۵ صداسنج</small></div>
    </footer>
  </div>;
}
