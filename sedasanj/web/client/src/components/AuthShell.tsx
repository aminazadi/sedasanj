import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import AuthAside from "./AuthAside";
import logo from "../assets/sedasanj-refined-master.svg";
import "../pages/Landing.css";
import "../pages/PublicPages.css";

/** Split layout shared by the sign-in and sign-up pages. */
export default function AuthShell({ children }: { children: ReactNode }) {
  return <div className="marketing-site auth-site" dir="rtl">
    <main className="auth-layout">
      <section className="auth-panel">
        <Link className="auth-logo" to="/" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></Link>
        <div className="auth-card">{children}</div>
        <nav className="auth-links" aria-label="پیوندهای کمکی"><Link to="/">صفحه اصلی</Link><Link to="/contact">تماس با ما</Link><Link to="/privacy">حریم خصوصی</Link></nav>
      </section>
      <AuthAside/>
    </main>
  </div>;
}
