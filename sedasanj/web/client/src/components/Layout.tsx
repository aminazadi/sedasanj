import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { isOperator, isOrgAdmin, ROLE_LABELS, useAuth } from "../auth";
import logo from "../assets/logo-small-fa.png";

type NavigationItem = {
  to: string;
  label: string;
  icon: string;
  orgAdminOnly?: boolean;
  hideForOperator?: boolean;
};

const NAVIGATION: Array<{ label: string; items: NavigationItem[] }> = [
  {
    label: "نمای کلی",
    items: [{ to: "/", label: "داشبورد", icon: "M3 13h8V3H3v10ZM13 21h8V11h-8v10ZM3 21h8v-6H3v6ZM13 9h8V3h-8v6Z" }],
  },
  {
    label: "مدیریت تماس‌ها",
    items: [
      { to: "/calls", label: "تماس‌ها", icon: "M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.69 2.8a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.33 1.85.56 2.81.69A2 2 0 0 1 22 16.92Z" },
      { to: "/tasks", label: "کارها", icon: "M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" },
      { to: "/assistant", label: "دستیار تماس‌ها", icon: "M12 2a8 8 0 0 0-8 8v4a4 4 0 0 0 4 4h1v-6H6v-2a6 6 0 0 1 12 0v2h-3v6h3a4 4 0 0 0 4-4v-4A10 10 0 0 0 12 2ZM9 21h6" },
    ],
  },
  {
    label: "گزارش و ارزیابی",
    items: [
      { to: "/analytics", label: "تحلیل‌ها", icon: "M3 3v18h18M7 16l4-5 4 3 5-7M17 7h3v3" },
      { to: "/operator-scores", label: "امتیازها", icon: "m12 2 3.09 6.26L22 9.27l-5 4.87L18.18 21 12 17.77 5.82 21 7 14.14l-5-4.87 6.91-1.01L12 2Z" },
      { to: "/kpi-settings", label: "تنظیمات KPI", icon: "M4 19V9M10 19V5M16 19v-7M22 19V2", orgAdminOnly: true },
    ],
  },
  {
    label: "حساب و سامانه",
    items: [
      { to: "/profile", label: "پروفایل من", icon: "M20 21a8 8 0 0 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z" },
      { to: "/account", label: "حساب کاربری", icon: "M20 21a8 8 0 0 0-16 0M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z", hideForOperator: true },
      { to: "/install", label: "راه‌اندازی", icon: "M14.7 6.3a4 4 0 0 0-5-5L7.4 3.6l3 3 2.3-2.3M5.5 8.5l-3.8 3.8a2.4 2.4 0 0 0 0 3.4l6.6 6.6a2.4 2.4 0 0 0 3.4 0l3.8-3.8M14 12l6.3 6.3a2.4 2.4 0 0 1-3.4 3.4l-6.3-6.3", hideForOperator: true },
      { to: "/api-docs", label: "مستندات API", icon: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 13h8M8 17h6" },
    ],
  },
];

const PAGE_TITLES: Record<string, string> = {
  "/checkout": "پرداخت و تمدید",
  "/payment-result": "نتیجه پرداخت",
  "/about": "درباره ما",
  "/contact": "تماس با ما",
  "/terms": "قوانین استفاده",
  "/privacy": "حریم خصوصی",
  "/cancellation": "سیاست لغو اشتراک",
};

function getPageTitle(pathname: string) {
  if (pathname.startsWith("/calls/")) return "جزئیات تماس";
  const navigationItem = NAVIGATION.flatMap((group) => group.items).find((item) => item.to === pathname);
  return navigationItem?.label ?? PAGE_TITLES[pathname] ?? "پنل کاربری";
}

function MenuIcon({ close = false }: { close?: boolean }) {
  return (
    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      {close ? <><path d="m18 6-12 12" /><path d="m6 6 12 12" /></> : <><path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h16" /></>}
    </svg>
  );
}

function Sidebar({ closeMenu }: { closeMenu?: () => void }) {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const operator = isOperator(session?.role);
  const orgAdmin = isOrgAdmin(session?.role);
  const roleLabel = operator ? "پنل اپراتور" : ROLE_LABELS[session?.role ?? ""] ?? session?.role;

  return (
    <div className="panel-sidebar flex h-full flex-col overflow-hidden text-white">
      <div className="relative flex h-[96px] shrink-0 items-center justify-center border-b border-[#B2AC88] px-5">
        <img className="w-36 invert mix-blend-screen" src={logo} alt="صدا سنج" />
        {closeMenu && (
          <button type="button" className="absolute left-4 p-2 text-[#F2F0EF] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" onClick={closeMenu} aria-label="بستن منو">
            <MenuIcon close />
          </button>
        )}
      </div>

      <nav className="sidebar-scroll flex-1 overflow-y-auto px-3 py-5" aria-label="منوی اصلی">
        {NAVIGATION.map((group) => {
          const items = group.items.filter((item) => !(operator && item.hideForOperator) && (!item.orgAdminOnly || orgAdmin));
          if (!items.length) return null;
          return (
            <div className="mb-5" key={group.label}>
              <p className="mb-2 px-3 text-[11px] font-medium text-[#B2AC88]">{group.label}</p>
              <div className="space-y-1">
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) => `sidebar-nav-item group flex items-center gap-3 px-3 py-2.5 text-sm transition-colors duration-200 ${isActive ? "bg-[#F2F0EF] font-bold text-[#4B6E48]" : "text-[#F2F0EF]"}`}
                  >
                    {({ isActive }) => (
                      <>
                        <svg className={`h-5 w-5 shrink-0 ${isActive ? "text-[#4B6E48]" : "text-[#B2AC88] transition group-hover:text-[#F2F0EF]"}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={item.icon} /></svg>
                        <span className="truncate">{item.label}</span>
                        {isActive && <span className="mr-auto h-1.5 w-1.5 shrink-0 bg-[#4B6E48]" />}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          );
        })}
      </nav>

      <div className="shrink-0 border-t border-[#B2AC88] p-3">
        <div className="flex items-center gap-3 p-3 text-[#F2F0EF]">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center bg-[#F2F0EF] text-sm font-bold text-[#4B6E48]">{roleLabel?.slice(0, 2) || "کا"}</div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{roleLabel}</p>
            <p className="truncate text-xs text-[#F2F0EF]">شناسه: {session?.userId.slice(0, 8)}</p>
          </div>
          <button
            type="button"
            className="p-2 text-[#F2F0EF] transition hover:bg-[#F2F0EF] hover:text-[#4B6E48]"
            aria-label="خروج از حساب کاربری"
            title="خروج"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m10 17 5-5-5-5M15 12H3M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /></svg>
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const pageTitle = getPageTitle(location.pathname);

  useEffect(() => setMenuOpen(false), [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  return (
    <div className="panel-shell min-h-screen lg:pr-72">
      <aside className="fixed inset-y-0 right-0 z-40 hidden w-72 lg:block"><Sidebar /></aside>

      <div className={`fixed inset-0 z-50 lg:hidden ${menuOpen ? "pointer-events-auto" : "pointer-events-none"}`} aria-hidden={!menuOpen}>
        <button type="button" className={`absolute inset-0 bg-slate-950/60 backdrop-blur-sm transition-opacity duration-300 ${menuOpen ? "opacity-100" : "opacity-0"}`} onClick={() => setMenuOpen(false)} aria-label="بستن منو" tabIndex={menuOpen ? 0 : -1} />
        <aside id="client-mobile-menu" className={`absolute inset-y-0 right-0 w-[min(88vw,19rem)] shadow-2xl transition-transform duration-300 ease-out ${menuOpen ? "visible translate-x-0" : "invisible translate-x-full"}`} role="dialog" aria-modal="true" aria-label="منوی کاربری">
          <Sidebar closeMenu={() => setMenuOpen(false)} />
        </aside>
      </div>

      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/90 backdrop-blur-xl lg:hidden">
        <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
          <button type="button" className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-700 shadow-sm transition hover:border-brand-200 hover:bg-brand-50 hover:text-brand-600" onClick={() => setMenuOpen(true)} aria-expanded={menuOpen} aria-controls="client-mobile-menu" aria-label="نمایش منو">
            <MenuIcon />
          </button>
          <h1 className="truncate text-base font-bold text-slate-900">{pageTitle}</h1>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7 lg:px-8 lg:py-8">{children}</main>
    </div>
  );
}
