import { useState, type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import logo from "../assets/logo-small-fa.png";

const NAV = [
  { to: "/", label: "داشبورد" },
  { to: "/tenants", label: "سازمان‌ها" },
  { to: "/tenant-databases", label: "دیتابیس سازمان‌ها" },
  { to: "/plans", label: "پلن‌ها" },
  { to: "/subscriptions", label: "اشتراک‌ها" },
  { to: "/commerce", label: "سفارش و پرداخت" },
  { to: "/packages", label: "بسته‌های اعتبار" },
  { to: "/sales", label: "فروش و سرنخ‌ها" },
  { to: "/installations", label: "نصب و استقرار" },
  { to: "/jobs", label: "عملیات پردازش" },
  { to: "/audit", label: "گزارش رویدادها" },
  { to: "/staff", label: "کاربران ادمین" },
  { to: "/commerce-settings", label: "تنظیمات تجاری" },
  { to: "/settings", label: "تنظیمات" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <header className="bg-slate-900 text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <img className="h-10 w-auto rounded bg-white px-2 py-1" src={logo} alt="صدا سنج" />
          <button className="mr-auto rounded-lg border border-slate-600 px-3 py-1.5 text-sm lg:hidden" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen} aria-label="نمایش منو">
            {menuOpen ? "بستن" : "منو"}
          </button>
          <nav className={`${menuOpen ? "flex" : "hidden"} order-last w-full flex-col gap-1 lg:order-none lg:flex lg:w-auto lg:flex-1 lg:flex-row lg:flex-wrap`}>
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm ${
                    isActive ? "bg-white/15 text-white" : "text-slate-300 hover:bg-white/10"
                  }`
                }
                onClick={() => setMenuOpen(false)}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <span className="hidden text-xs text-slate-400 sm:inline">{session?.role}</span>
          <button
            className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm hover:bg-white/10"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            خروج
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
    </div>
  );
}
