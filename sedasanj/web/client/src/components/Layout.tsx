import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Icon, type IconifyIcon } from "@iconify/react";
import bookUserIcon from "@iconify-icons/lucide/book-user";
import botIcon from "@iconify-icons/lucide/bot";
import calendarClockIcon from "@iconify-icons/lucide/calendar-clock";
import dashboardIcon from "@iconify-icons/lucide/layout-dashboard";
import fileTextIcon from "@iconify-icons/lucide/file-text";
import historyIcon from "@iconify-icons/lucide/history";
import logOutIcon from "@iconify-icons/lucide/log-out";
import menuIcon from "@iconify-icons/lucide/menu";
import phoneIcon from "@iconify-icons/lucide/phone";
import rocketIcon from "@iconify-icons/lucide/rocket";
import serverIcon from "@iconify-icons/lucide/server";
import settingsIcon from "@iconify-icons/lucide/settings";
import tasksIcon from "@iconify-icons/lucide/list-checks";
import trophyIcon from "@iconify-icons/lucide/trophy";
import userIcon from "@iconify-icons/lucide/user-round";
import walletIcon from "@iconify-icons/lucide/wallet";
import closeIcon from "@iconify-icons/lucide/x";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { isOperator, isOrgAdmin, ROLE_LABELS, useAuth } from "../auth";
import { BrandLogo } from "./BrandLogo";
import ModuleUpdateBanner from "./ModuleUpdateBanner";
import QuickAssistantWidget from "./QuickAssistantWidget";

type NavigationItem = {
  to: string;
  label: string;
  icon: IconifyIcon;
  orgAdminOnly?: boolean;
  hideForOperator?: boolean;
};

const NAVIGATION: Array<{ label: string; items: NavigationItem[] }> = [
  {
    label: "نمای کلی",
    items: [{ to: "/", label: "داشبورد", icon: dashboardIcon }],
  },
  {
    label: "مدیریت تماس‌ها",
    items: [
      { to: "/calls", label: "تماس‌ها", icon: phoneIcon },
      { to: "/contacts", label: "دفترچه تلفن", icon: bookUserIcon },
      { to: "/tasks", label: "کارها", icon: tasksIcon },
      { to: "/assistant", label: "دستیار تماس‌ها", icon: botIcon },
    ],
  },
  {
    label: "گزارش و ارزیابی",
    items: [
      { to: "/scheduled-reports", label: "گزارش‌های زمان‌بندی‌شده", icon: calendarClockIcon, orgAdminOnly: true },
      { to: "/operator-scores", label: "امتیازها", icon: trophyIcon },
    ],
  },
  {
    label: "حساب و تنظیمات",
    items: [
      { to: "/profile", label: "پروفایل من", icon: userIcon },
      { to: "/account", label: "اعتبار و اشتراک", icon: walletIcon, hideForOperator: true },
      { to: "/account-settings", label: "تنظیمات حساب", icon: settingsIcon, orgAdminOnly: true },
      { to: "/install", label: "راه‌اندازی", icon: rocketIcon, hideForOperator: true },
      { to: "/freepbx-servers", label: "سرورهای FreePBX", icon: serverIcon, orgAdminOnly: true },
      { to: "/module-changelog", label: "تغییرات نسخه‌ها", icon: historyIcon, hideForOperator: true },
      { to: "/api-docs", label: "مستندات API", icon: fileTextIcon },
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

type DesktopMenuToggle = {
  open: boolean;
  toggle: () => void;
};

const DesktopMenuToggleContext = createContext<DesktopMenuToggle | null>(null);
const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const LATIN_DIGIT_PATTERN = /[0-9]/g;
const LATIN_DIGIT_EXCLUSIONS = "input, textarea, select, option, code, pre, kbd, samp, [contenteditable='true'], [data-keep-latin-digits]";

export function useDesktopMenuToggle() {
  return useContext(DesktopMenuToggleContext);
}

function localizePanelDigits(root: HTMLElement) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let node = walker.nextNode();
  while (node) {
    nodes.push(node as Text);
    node = walker.nextNode();
  }
  for (const textNode of nodes) {
    if (textNode.parentElement?.closest(LATIN_DIGIT_EXCLUSIONS)) continue;
    const text = textNode.data;
    if (!/[0-9]/.test(text)) continue;
    textNode.data = text.replace(LATIN_DIGIT_PATTERN, (digit) => PERSIAN_DIGITS[Number(digit)]);
  }
}

function getPageTitle(pathname: string) {
  if (pathname.startsWith("/calls/")) return "جزئیات تماس";
  const navigationItem = NAVIGATION.flatMap((group) => group.items).find((item) => item.to === pathname);
  return navigationItem?.label ?? PAGE_TITLES[pathname] ?? "پنل کاربری";
}

function MenuIcon({ close = false }: { close?: boolean }) {
  return <Icon icon={close ? closeIcon : menuIcon} className="h-6 w-6" aria-hidden="true" />;
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
        <BrandLogo animated className="panel-brand-logo w-36" color="#f2f0ef" title="صدا سنج" />
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
                        <Icon icon={item.icon} className={`h-5 w-5 shrink-0 ${isActive ? "text-[#4B6E48]" : "text-[#B2AC88] transition group-hover:text-[#F2F0EF]"}`} aria-hidden="true" />
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
            <p className="truncate text-xs text-[#B2AC88]">شناسه: {session?.userId.slice(0, 8)}</p>
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
            <Icon icon={logOutIcon} className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const panelRef = useRef<HTMLDivElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const isAssistantPage = location.pathname === "/assistant";
  const [desktopMenuOpen, setDesktopMenuOpen] = useState(() => location.pathname !== "/assistant");
  const pageTitle = getPageTitle(location.pathname);
  const { session } = useAuth();
  const orgAdmin = isOrgAdmin(session?.role);

  useEffect(() => setMenuOpen(false), [location.pathname]);

  useEffect(() => setDesktopMenuOpen(!isAssistantPage), [isAssistantPage]);

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

  useEffect(() => {
    const panel = panelRef.current;
    if (!panel) return;
    const localize = () => localizePanelDigits(panel);
    localize();
    const observer = new MutationObserver(localize);
    observer.observe(panel, { childList: true, characterData: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  return (
    <DesktopMenuToggleContext.Provider value={isAssistantPage ? { open: desktopMenuOpen, toggle: () => setDesktopMenuOpen((open) => !open) } : null}>
      <div ref={panelRef} className={`panel-shell min-h-screen transition-[padding] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] ${isAssistantPage && !desktopMenuOpen ? "lg:pr-0" : "lg:pr-72"}`} lang="fa">
        <aside id="client-desktop-menu" className={`fixed inset-y-0 right-0 z-40 hidden w-72 transition-[transform,opacity] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] lg:block ${isAssistantPage && !desktopMenuOpen ? "pointer-events-none translate-x-full opacity-0" : "translate-x-0 opacity-100"}`}><Sidebar /></aside>

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

        <main className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7 lg:px-8 lg:py-8">{orgAdmin && !isAssistantPage ? <ModuleUpdateBanner /> : null}{children}</main>
        {!isAssistantPage ? <QuickAssistantWidget /> : null}
      </div>
    </DesktopMenuToggleContext.Provider>
  );
}
