import { useEffect, useLayoutEffect, useRef, useState, type FocusEvent, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon, type IconifyIcon } from "@iconify/react";
import bookUserIcon from "@iconify-icons/lucide/book-user";
import botIcon from "@iconify-icons/lucide/bot";
import calendarClockIcon from "@iconify-icons/lucide/calendar-clock";
import dashboardIcon from "@iconify-icons/lucide/layout-dashboard";
import extensionIcon from "@iconify-icons/lucide/phone-forwarded";
import fileTextIcon from "@iconify-icons/lucide/file-text";
import historyIcon from "@iconify-icons/lucide/history";
import logOutIcon from "@iconify-icons/lucide/log-out";
import menuIcon from "@iconify-icons/lucide/menu";
import meetingsIcon from "@iconify-icons/lucide/notebook-pen";
import panelCloseIcon from "@iconify-icons/lucide/panel-right-close";
import panelOpenIcon from "@iconify-icons/lucide/panel-right-open";
import phoneIcon from "@iconify-icons/lucide/phone";
import rocketIcon from "@iconify-icons/lucide/rocket";
import serverIcon from "@iconify-icons/lucide/server";
import settingsIcon from "@iconify-icons/lucide/settings";
import tasksIcon from "@iconify-icons/lucide/list-checks";
import trophyIcon from "@iconify-icons/lucide/trophy";
import userIcon from "@iconify-icons/lucide/user-round";
import voicemailIcon from "@iconify-icons/lucide/voicemail";
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
      { to: "/voicemails", label: "پیام‌های صوتی", icon: voicemailIcon },
      { to: "/meetings", label: "جلسات", icon: meetingsIcon },
      { to: "/contacts", label: "دفترچه تلفن", icon: bookUserIcon },
      { to: "/extensions", label: "داخلی‌ها", icon: extensionIcon },
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
      { to: "/account-settings", label: "تنظیمات حساب", icon: settingsIcon },
      { to: "/install", label: "راه‌اندازی", icon: rocketIcon, hideForOperator: true },
      { to: "/freepbx-servers", label: "سرورهای تلفنی", icon: serverIcon, orgAdminOnly: true },
      { to: "/module-changelog", label: "تغییرات نسخه‌ها", icon: historyIcon, hideForOperator: true },
      { to: "/api-docs", label: "مستندات API", icon: fileTextIcon },
    ],
  },
];

const PAGE_TITLES: Record<string, string> = {
  "/account-settings/data/history": "تاریخچهٔ بک‌آپ و بازیابی",
  "/checkout": "پرداخت و تمدید",
  "/payment-result": "نتیجه پرداخت",
  "/about": "درباره ما",
  "/contact": "تماس با ما",
  "/terms": "قوانین استفاده",
  "/privacy": "حریم خصوصی",
  "/cancellation": "سیاست لغو اشتراک",
};

const SIDEBAR_COLLAPSED_KEY = "sedasanj.client.sidebarCollapsed";

function readSidebarCollapsed() {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function writeSidebarCollapsed(collapsed: boolean) {
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    // Storage can be blocked; the preference then lasts for this page view only.
  }
}

const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
const LATIN_DIGIT_PATTERN = /[0-9]/g;
const LATIN_DIGIT_EXCLUSIONS = "input, textarea, select, option, code, pre, kbd, samp, [contenteditable='true'], [data-keep-latin-digits]";

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
  if (pathname.startsWith("/meetings/")) return "جزئیات جلسه";
  const navigationItem = NAVIGATION.flatMap((group) => group.items).find((item) => item.to === pathname);
  return navigationItem?.label ?? PAGE_TITLES[pathname] ?? "پنل کاربری";
}

function MenuIcon({ close = false }: { close?: boolean }) {
  return <Icon icon={close ? closeIcon : menuIcon} className="h-6 w-6" aria-hidden="true" />;
}

type SidebarTooltip = { label: string; target: HTMLElement };

function Sidebar({ closeMenu, collapsed = false, onToggleCollapse }: { closeMenu?: () => void; collapsed?: boolean; onToggleCollapse?: () => void }) {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const operator = isOperator(session?.role);
  const orgAdmin = isOrgAdmin(session?.role);
  const [tooltip, setTooltip] = useState<SidebarTooltip | null>(null);
  const showTooltip = (label: string | undefined, target: HTMLElement) => {
    if (!collapsed || !label) return;
    setTooltip((current) => current?.target === target && current.label === label ? current : { label, target });
  };
  const showPointerTooltip = (label: string | undefined) => (event: PointerEvent<HTMLElement>) => {
    if (event.pointerType === "touch") return;
    showTooltip(label, event.currentTarget);
  };
  const showFocusTooltip = (label: string | undefined) => (event: FocusEvent<HTMLElement>) => {
    if (!event.currentTarget.matches(":focus-visible")) return;
    showTooltip(label, event.currentTarget);
  };
  const tooltipRef = useRef<HTMLDivElement>(null);
  const hideTooltip = () => setTooltip(null);
  useEffect(() => {
    setTooltip(null);
  }, [collapsed, location.key]);
  useEffect(() => {
    if (!tooltip) return;
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTooltip(null);
    };
    window.addEventListener("keydown", dismiss);
    return () => window.removeEventListener("keydown", dismiss);
  }, [tooltip]);
  // Keep the tooltip glued to its item even when the layout shifts underneath it.
  useLayoutEffect(() => {
    if (!tooltip) return;
    let frame = 0;
    const follow = () => {
      const node = tooltipRef.current;
      const { target } = tooltip;
      if (!target.isConnected) {
        setTooltip(null);
        return;
      }
      if (node) {
        const rect = target.getBoundingClientRect();
        node.style.top = `${rect.top}px`;
        node.style.right = `${window.innerWidth - rect.left + 8}px`;
        node.style.height = `${rect.height}px`;
      }
      frame = window.requestAnimationFrame(follow);
    };
    follow();
    return () => window.cancelAnimationFrame(frame);
  }, [tooltip]);
  const roleLabel = operator ? "پنل اپراتور" : ROLE_LABELS[session?.role ?? ""] ?? session?.role;

  return (
    <>
    <div className="panel-sidebar flex h-full flex-col overflow-hidden text-white">
      <div className={`relative flex shrink-0 items-center justify-center border-b border-white/10 ${collapsed ? "flex-col gap-2 px-2 py-3" : "h-[96px] px-5"}`}>
        {collapsed ? (
          <div className="relative h-32 w-14 shrink-0">
            <div className="absolute left-1/2 top-1/2 w-32 -translate-x-1/2 -translate-y-1/2 -rotate-90">
              <BrandLogo animated className="panel-brand-logo block w-full" color="#f2f0ef" title="صدا سنج" />
            </div>
          </div>
        ) : (
          <BrandLogo animated className="panel-brand-logo w-36" color="#f2f0ef" title="صدا سنج" />
        )}
        {onToggleCollapse && (
          <button
            type="button"
            className={`sb-round p-2 text-[#F2F0EF] transition hover:bg-white/15 ${collapsed ? "order-first" : "absolute left-4"}`}
            onClick={() => { hideTooltip(); onToggleCollapse(); }}
            aria-label={collapsed ? "باز کردن منو" : "کوچک کردن منو"}
            aria-expanded={!collapsed}
            onPointerEnter={showPointerTooltip(collapsed ? "باز کردن منو" : undefined)}
            onFocus={showFocusTooltip(collapsed ? "باز کردن منو" : undefined)}
            onPointerLeave={hideTooltip}
            onBlur={hideTooltip}
          >
            <Icon icon={collapsed ? panelOpenIcon : panelCloseIcon} className="h-5 w-5" aria-hidden="true" />
          </button>
        )}
        {closeMenu && (
          <button type="button" className="sb-round absolute left-4 p-2 text-[#F2F0EF] transition hover:bg-white/15" onClick={closeMenu} aria-label="بستن منو">
            <MenuIcon close />
          </button>
        )}
      </div>

      <nav className={`sidebar-scroll flex-1 overflow-y-auto py-4 ${collapsed ? "px-2" : "px-3"}`} aria-label="منوی اصلی">
        {NAVIGATION.map((group) => {
          const items = group.items.filter((item) => !(operator && item.hideForOperator) && (!item.orgAdminOnly || orgAdmin));
          if (!items.length) return null;
          return (
            <div className={collapsed ? "mb-4 border-b border-white/10 pb-4 last:border-b-0" : "mb-6"} key={group.label}>
              {!collapsed && <p className="mb-2 px-3 text-[11px] font-medium tracking-wide text-[#D5D0AE]/80">{group.label}</p>}
              <div className="space-y-0.5">
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    onPointerEnter={showPointerTooltip(item.label)}
                    onFocus={showFocusTooltip(item.label)}
                    onPointerLeave={hideTooltip}
                    onBlur={hideTooltip}
                    onClick={() => { hideTooltip(); closeMenu?.(); }}
                    aria-label={collapsed ? item.label : undefined}
                    className={({ isActive }) => `sidebar-nav-item sb-round group relative flex items-center ${collapsed ? "justify-center px-0" : "gap-3 px-3"} py-2.5 text-sm transition-colors duration-200 ${isActive ? "is-active bg-white/15 font-bold text-white" : "text-[#F2F0EF]/85"}`}
                  >
                    {({ isActive }) => (
                      <>
                        <Icon icon={item.icon} className={`h-5 w-5 shrink-0 ${isActive ? "text-[#E3E8B9]" : "text-[#F2F0EF]/65 transition group-hover:text-white"}`} aria-hidden="true" />
                        {!collapsed && <span className="truncate">{item.label}</span>}
                        {isActive && <span className="sb-round absolute inset-y-2 right-0 w-[3px] bg-[#E3E8B9]" />}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          );
        })}
      </nav>

      <div className="shrink-0 border-t border-white/10 p-3">
        <div className={`sb-round flex items-center bg-black/10 text-[#F2F0EF] ${collapsed ? "flex-col gap-2 p-1.5" : "gap-3 p-2.5"}`} onPointerEnter={showPointerTooltip(roleLabel)} onPointerLeave={hideTooltip}>
          <div className="sb-round flex h-10 w-10 shrink-0 items-center justify-center bg-gradient-to-br from-[#F2F0EF] to-[#D5D0AE] text-sm font-bold text-[#4B6E48]">{roleLabel?.slice(0, 2) || "کا"}</div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{roleLabel}</p>
              <p className="truncate text-xs text-[#F2F0EF]/55">شناسه: {session?.userId.slice(0, 8)}</p>
            </div>
          )}
          <button
            type="button"
            className="sb-round p-2 text-[#F2F0EF]/80 transition hover:bg-white/15 hover:text-white"
            aria-label="خروج از حساب کاربری"
            onPointerEnter={showPointerTooltip(collapsed ? "خروج" : undefined)}
            onFocus={showFocusTooltip(collapsed ? "خروج" : undefined)}
            onPointerLeave={hideTooltip}
            onBlur={hideTooltip}
            onClick={async () => {
              hideTooltip();
              await logout();
              navigate("/login");
            }}
          >
            <Icon icon={logOutIcon} className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
    {tooltip ? createPortal(<div key={tooltip.label} ref={tooltipRef} role="tooltip" className="sidebar-tooltip pointer-events-none fixed z-[70] flex items-center whitespace-nowrap border border-white/15 bg-[#4B6E48] px-4 text-sm font-bold text-white shadow-lg" style={{ top: 0, right: 0 }}>{tooltip.label}</div>, document.body) : null}
    </>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const panelRef = useRef<HTMLDivElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const isAssistantPage = location.pathname === "/assistant";
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  // The assistant page opens minimal; expanding it there does not change the saved preference.
  const [assistantExpanded, setAssistantExpanded] = useState(false);
  useEffect(() => setAssistantExpanded(false), [isAssistantPage]);
  const desktopCollapsed = isAssistantPage ? !assistantExpanded : sidebarCollapsed;
  const toggleSidebarCollapsed = () => {
    setSidebarCollapsed((collapsed) => {
      writeSidebarCollapsed(!collapsed);
      return !collapsed;
    });
  };
  const pageTitle = getPageTitle(location.pathname);
  const { session } = useAuth();
  const orgAdmin = isOrgAdmin(session?.role);

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
    <>
      <div ref={panelRef} className={`panel-shell min-h-screen transition-[padding] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] ${desktopCollapsed ? "lg:pr-20" : "lg:pr-72"}`} lang="fa">
        <aside id="client-desktop-menu" className={`fixed inset-y-0 right-0 z-40 hidden ${desktopCollapsed ? "w-20" : "w-72"} transition-[width] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] lg:block`}><Sidebar collapsed={desktopCollapsed} onToggleCollapse={isAssistantPage ? () => setAssistantExpanded((expanded) => !expanded) : toggleSidebarCollapsed} /></aside>

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
    </>
  );
}
