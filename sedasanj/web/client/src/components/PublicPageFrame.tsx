import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import logo from "../assets/logo-small-fa.png";

function ArrowIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>;
}

function MenuIcon({ close }: { close: boolean }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">{close ? <><path d="m6 6 12 12"/><path d="M18 6 6 18"/></> : <><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/></>}</svg>;
}

export default function PublicPageFrame({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [location.pathname]);

  return <div className="landing public-page" dir="rtl">
    <header className="landing-header"><div className="landing-container landing-nav">
      <Link className="landing-brand" to="/" aria-label="صداسنج، صفحه اصلی"><img src={logo} alt="صداسنج" /></Link>
      <nav className={menuOpen ? "landing-links is-open" : "landing-links"} aria-label="دسترسی اصلی">
        <Link to="/#features">امکانات</Link>
        <Link to="/#pricing">پلن‌ها</Link>
        <Link className={location.pathname === "/about" ? "is-active" : ""} to="/about">درباره ما</Link>
        <Link className={location.pathname === "/contact" ? "is-active" : ""} to="/contact">تماس با ما</Link>
        <Link className="mobile-login-link" to="/login">ورود به پنل <ArrowIcon/></Link>
      </nav>
      <div className="landing-nav-actions"><Link className="landing-login" to="/login">ورود به پنل <ArrowIcon/></Link><button className="landing-menu" type="button" aria-label={menuOpen ? "بستن فهرست" : "باز کردن فهرست"} aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}><MenuIcon close={menuOpen}/></button></div>
    </div></header>

    {children}

    <footer className="landing-footer"><div className="landing-container footer-row"><Link to="/"><img src={logo} alt="صداسنج"/></Link><p>سامانه هوشمند تحلیل مکالمات فارسی</p><div><Link to="/#features">امکانات</Link><Link to="/#pricing">پلن‌ها</Link><Link to="/about">درباره ما</Link><Link to="/contact">تماس با ما</Link><Link to="/login">ورود</Link></div><small>© ۱۴۰۵ صداسنج</small></div></footer>
  </div>;
}
