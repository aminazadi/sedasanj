import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import SiteFooter from "./SiteFooter";
import { Icon } from "./SiteIcon";
import logo from "../assets/sedasanj-refined-master.webp";
import "../pages/Landing.css";
import "../pages/PublicPages.css";

function MenuIcon({ close }: { close: boolean }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">{close ? <><path d="m6 6 12 12"/><path d="M18 6 6 18"/></> : <><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/></>}</svg>;
}

/** Header and footer shared by every public page except the landing page itself. */
export default function PublicPageFrame({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [location.pathname]);
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

    <SiteFooter />
  </div>;
}
