import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import logo from "../assets/logo-small-fa.png";

type NavigationGroup = {
  label: string;
  items: Array<{ to: string; label: string; icon: ReactNode }>;
};

const icons = {
  dashboard: <><path d="M3 13h8V3H3v10ZM13 21h8V11h-8v10ZM3 21h8v-6H3v6ZM13 9h8V3h-8v6Z" /></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
  database: <><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3" /></>,
  book: <><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /></>,
  repeat: <><path d="M20 12a8 8 0 1 1-2.34-5.66L20 8.68M20 4v4.68h-4.68" /></>,
  card: <><rect width="20" height="14" x="2" y="5" rx="2" /><path d="M2 10h20M6 15h2" /></>,
  package: <><path d="m21 8-9-5-9 5 9 5 9-5ZM3 8v8l9 5 9-5V8M12 13v8" /></>,
  chart: <><path d="M3 3v18h18M7 16l4-5 4 3 5-7M17 7h3v3" /></>,
  tool: <><path d="M14.7 6.3a4 4 0 0 0-5-5L7.4 3.6l3 3 2.3-2.3M5.5 8.5l-3.8 3.8a2.4 2.4 0 0 0 0 3.4l6.6 6.6a2.4 2.4 0 0 0 3.4 0l3.8-3.8M14 12l6.3 6.3a2.4 2.4 0 0 1-3.4 3.4l-6.3-6.3" /></>,
  jobs: <><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M9 3v18m5-13 3 4-3 4" /></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8ZM14 2v6h6M8 13h8M8 17h6" /></>,
  staff: <><circle cx="12" cy="8" r="4" /><path d="M5 21a7 7 0 0 1 14 0M18 5h4M20 3v4" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1.4 1.6H9.6A1.7 1.7 0 0 0 8 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15 1.7 1.7 0 0 0 3 13.6V10.4A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10.4 3h3.2A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.6 1.4v3.2a1.7 1.7 0 0 0-1.6 1.4Z" /></>,
};

const NAVIGATION: NavigationGroup[] = [
  { label: "نمای کلی", items: [{ to: "/", label: "داشبورد", icon: icons.dashboard }] },
  {
    label: "مدیریت سازمان‌ها",
    items: [
      { to: "/tenants", label: "سازمان‌ها", icon: icons.users },
      { to: "/tenant-databases", label: "دیتابیس سازمان‌ها", icon: icons.database },
      { to: "/staff", label: "کاربران ادمین", icon: icons.staff },
    ],
  },
  {
    label: "فروش و درآمد",
    items: [
      { to: "/plans", label: "پلن‌ها", icon: icons.book },
      { to: "/subscriptions", label: "اشتراک‌ها", icon: icons.repeat },
      { to: "/commerce", label: "سفارش و پرداخت", icon: icons.card },
      { to: "/packages", label: "بسته‌های اعتبار", icon: icons.package },
      { to: "/sales", label: "فروش و سرنخ‌ها", icon: icons.chart },
      { to: "/installations", label: "نصب و استقرار", icon: icons.tool },
    ],
  },
  {
    label: "سیستم",
    items: [
      { to: "/jobs", label: "عملیات پردازش", icon: icons.jobs },
      { to: "/audit", label: "گزارش رویدادها", icon: icons.file },
      { to: "/commerce-settings", label: "تنظیمات تجاری", icon: icons.settings },
      { to: "/settings", label: "تنظیمات", icon: icons.settings },
    ],
  },
];

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

  return (
    <div className="panel-sidebar flex h-full flex-col overflow-hidden text-white">
      <div className="relative flex h-[96px] shrink-0 items-center justify-center border-b border-white/10 px-5">
        <img className="w-36 invert mix-blend-screen" src={logo} alt="صدا سنج" />
        {closeMenu && (
          <button type="button" className="absolute left-4 rounded-xl p-2 text-slate-400 transition hover:bg-white/10 hover:text-white" onClick={closeMenu} aria-label="بستن منو">
            <MenuIcon close />
          </button>
        )}
      </div>

      <nav className="sidebar-scroll flex-1 overflow-y-auto px-3 py-5" aria-label="منوی اصلی">
        {NAVIGATION.map((group) => (
          <div className="mb-5" key={group.label}>
            <p className="mb-2 px-3 text-[11px] font-medium text-slate-500">{group.label}</p>
            <div className="space-y-1">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) => `group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all duration-200 ${isActive ? "bg-brand-500 text-white shadow-lg shadow-brand-950/30" : "text-slate-300 hover:bg-white/[0.07] hover:text-white"}`}
                >
                  {({ isActive }) => (
                    <>
                      <svg className={`h-5 w-5 shrink-0 ${isActive ? "text-white" : "text-slate-400 transition group-hover:text-brand-300"}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{item.icon}</svg>
                      <span className="truncate">{item.label}</span>
                      {isActive && <span className="mr-auto h-1.5 w-1.5 shrink-0 rounded-full bg-white" />}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-white/10 p-3">
        <div className="flex items-center gap-3 rounded-2xl bg-white/[0.06] p-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-500/20 text-sm font-bold text-brand-300">{session?.role?.slice(0, 2).toUpperCase() || "AD"}</div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">مدیر سامانه</p>
            <p className="truncate text-xs text-slate-400">{session?.role}</p>
          </div>
          <button
            type="button"
            className="rounded-xl p-2 text-slate-400 transition hover:bg-rose-500/15 hover:text-rose-300"
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
        <aside id="admin-mobile-menu" className={`absolute inset-y-0 right-0 w-[min(88vw,19rem)] shadow-2xl transition-transform duration-300 ease-out ${menuOpen ? "visible translate-x-0" : "invisible translate-x-full"}`} role="dialog" aria-modal="true" aria-label="منوی مدیریت">
          <Sidebar closeMenu={() => setMenuOpen(false)} />
        </aside>
      </div>

      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/90 backdrop-blur-xl lg:hidden">
        <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
          <button type="button" className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white text-slate-700 shadow-sm transition hover:border-brand-200 hover:bg-brand-50 hover:text-brand-600" onClick={() => setMenuOpen(true)} aria-expanded={menuOpen} aria-controls="admin-mobile-menu" aria-label="نمایش منو">
            <MenuIcon />
          </button>
          <div className="h-9 w-9 rounded-xl border border-slate-100 bg-white p-1 shadow-sm"><img className="h-full w-full object-contain" src={logo} alt="" /></div>
          <div>
            <p className="text-sm font-bold text-slate-900">پنل مدیریت</p>
            <p className="text-[11px] text-slate-500">صدا سنج</p>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7 lg:px-8 lg:py-8">{children}</main>
    </div>
  );
}
