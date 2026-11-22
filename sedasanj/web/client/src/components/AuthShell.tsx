import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import ThemeToggleButton from "./ThemeToggleButton";
import AuthAside from "./AuthAside";
import logo from "../assets/sedasanj-refined-master.webp";
import "../pages/Landing.css";
import "../pages/PublicPages.css";

/** Split layout shared by the sign-in and sign-up pages. */
export default function AuthShell({ children }: { children: ReactNode }) {
  return <div className="marketing-site auth-site" dir="rtl">
    <main className="auth-layout">
      <section className="auth-panel">
        <Link className="auth-logo" to="/" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></Link>
        <div className="auth-card">{children}</div>
        <div className="auth-footer">
          <nav className="auth-links" aria-label="پیوندهای کمکی"><Link to="/">صفحه اصلی</Link><Link to="/contact">تماس با ما</Link><Link to="/privacy">حریم خصوصی</Link></nav>
          <ThemeToggleButton className="auth-theme-switch"/>
        </div>
      </section>
      <AuthAside/>
    </main>
  </div>;
}
