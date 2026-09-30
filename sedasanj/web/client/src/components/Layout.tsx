import { NavLink, useNavigate } from "react-router-dom";
import { useState, type ReactNode } from "react";
import { isOperator, isOrgAdmin, ROLE_LABELS, useAuth } from "../auth";
import logo from "../assets/logo-small-fa.png";

const NAV: Array<{ to: string; label: string; orgAdminOnly?: boolean; hideForOperator?: boolean }> = [
  { to: "/", label: "نمای کلی" },
  { to: "/calls", label: "تماس‌ها" },
  { to: "/tasks", label: "کارها" },
  { to: "/analytics", label: "تحلیل‌ها" },
  { to: "/assistant", label: "دستیار تماس‌ها" },
  { to: "/operator-scores", label: "امتیازها" },
  { to: "/kpi-settings", label: "تنظیمات KPI", orgAdminOnly: true },
  { to: "/account", label: "حساب", hideForOperator: true },
  { to: "/install", label: "راه‌اندازی", hideForOperator: true },
  { to: "/api-docs", label: "مستندات API" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const operator = isOperator(session?.role);
  const orgAdmin = isOrgAdmin(session?.role);
  const items = NAV.filter((item) => !(operator && item.hideForOperator) && (!item.orgAdminOnly || orgAdmin));
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3 md:gap-6">
          <img className="h-10 w-auto" src={logo} alt="صدا سنج" />
          <button className="btn-ghost mr-auto inline-flex h-10 w-10 items-center justify-center md:hidden" type="button" aria-label={menuOpen ? "بستن منو" : "باز کردن منو"} aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}><span className="text-xl" aria-hidden="true">☰</span></button>
          <nav className={`${menuOpen ? "flex" : "hidden"} order-4 w-full flex-col gap-1 rounded-xl border border-slate-200 bg-slate-50 p-2 md:order-none md:flex md:w-auto md:flex-1 md:flex-row md:justify-start md:border-0 md:bg-transparent md:p-0`}>
            {items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-lg px-3 py-1.5 text-sm ${
                    isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <span className="text-xs text-slate-500">
            {operator ? "پنل اپراتور" : ROLE_LABELS[session?.role ?? ""] ?? session?.role}
          </span>
          <button
            className="btn-ghost text-sm"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            خروج
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
