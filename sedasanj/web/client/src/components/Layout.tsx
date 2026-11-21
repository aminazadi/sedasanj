import { canVisitPanel, hasPanelAccess } from "../lib/panelAccess";
import { useEffect, useLayoutEffect, useRef, useState, type FocusEvent, type PointerEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon, type IconifyIcon } from "@iconify/react";
import bookOpenIcon from "@iconify-icons/lucide/book-open";
import bookUserIcon from "@iconify-icons/lucide/book-user";
import botIcon from "@iconify-icons/lucide/bot";
import calendarClockIcon from "@iconify-icons/lucide/calendar-clock";
import dashboardIcon from "@iconify-icons/lucide/layout-dashboard";
import downloadIcon from "@iconify-icons/lucide/download";
import extensionIcon from "@iconify-icons/lucide/phone-forwarded";
import fileTextIcon from "@iconify-icons/lucide/file-text";
import historyIcon from "@iconify-icons/lucide/history";
import volumeOffIcon from "@iconify-icons/lucide/volume-x";
import volumeOnIcon from "@iconify-icons/lucide/volume-2";
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
import chevronDownIcon from "@iconify-icons/lucide/chevron-down";
import closeIcon from "@iconify-icons/lucide/x";
import circleHelpIcon from "@iconify-icons/lucide/circle-help";
import monitorIcon from "@iconify-icons/lucide/monitor";
import moonIcon from "@iconify-icons/lucide/moon";
import sunIcon from "@iconify-icons/lucide/sun";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { getMenuSound, menuSoundLabel, nextMenuSound, playMenuTick, setMenuSound } from "../lib/menuSound";
import { isOperator, isOrgAdmin, ROLE_LABELS, useAuth } from "../auth";
import { request } from "../api";
import { hasCompletedTour } from "../lib/guideTourState.mjs";
import { useTheme, type ThemeMode } from "@cbi/web-shared/lib/theme";
import { BrandLogo } from "./BrandLogo";
import BillingBanner from "./BillingBanner";
import GuideTour from "./GuideTour";
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
      { to: "/contacts", label: "دفترچه تلفن", icon: bookUserIcon },
      { to: "/extensions", label: "داخلی‌ها", icon: extensionIcon },
      { to: "/tasks", label: "کارها", icon: tasksIcon },
      { to: "/assistant", label: "دستیار تماس‌ها", icon: botIcon },
    ],
  },
  {
    label: "جلسه‌نگار",
    items: [
      { to: "/meetings", label: "صورت‌جلسات عمومی", icon: meetingsIcon },
      { to: "/jalase-negar-install", label: "راهنمای نصب و دانلود", icon: downloadIcon },
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
      { to: "/help", label: "مقالات و آموزش‌ها", icon: bookOpenIcon },
      { to: "/api-docs", label: "مستندات API", icon: fileTextIcon },
    ],
  },
];

// Category items share the /meetings path with the plain list, so they are told apart by the query string.
function navItemActive(to: string, pathActive: boolean, search: string) {
  const [path, query] = to.split("?");
  const typeNow = new URLSearchParams(search).get("output_type");
  if (query) return pathActive && typeNow === new URLSearchParams(query).get("output_type");
  if (path === "/meetings") return pathActive && !typeNow;
  return pathActive;
}

const PAGE_TITLES: Record<string, string> = {
  "/account-settings/data/history": "تاریخچهٔ بک‌آپ و بازیابی",
  "/account/transactions": "تراکنش‌ها",
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
  if (pathname.startsWith("/help/")) return "مقالات و آموزش‌ها";
  if (pathname.startsWith("/calls/")) return "جزئیات تماس";
  if (pathname.startsWith("/meetings/")) return "جزئیات جلسه";
  const navigationItem = NAVIGATION.flatMap((group) => group.items).find((item) => item.to === pathname);
  return navigationItem?.label ?? PAGE_TITLES[pathname] ?? "پنل کاربری";
}

function MenuIcon({ close = false }: { close?: boolean }) {
  return <Icon icon={close ? closeIcon : menuIcon} className="h-6 w-6" aria-hidden="true" />;
}

type SidebarTooltip = { label: string; target: HTMLElement };
type SidebarPill = { top: number; left: number; width: number; height: number; visible: boolean; snap: boolean };

function Sidebar({ closeMenu, collapsed = false, onToggleCollapse, onReplayGuide }: { closeMenu?: () => void; collapsed?: boolean; onToggleCollapse?: () => void; onReplayGuide?: () => void }) {
  const { session, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const operator = isOperator(session?.role);
  const orgAdmin = isOrgAdmin(session?.role);
  // Jalase-Negar categories the organization has documents in; each gets a menu item next to general minutes in the "جلسه‌نگار" group.
  const [jalaseItems, setJalaseItems] = useState<NavigationItem[]>([]);
  useEffect(() => {
    if (!hasPanelAccess(session, "meetings")) return;
    let cancelled = false;
    request<{ items: Array<{ code: string; label: string }> }>("/v1/jalase/org-menu")
      .then((menu) => {
        if (cancelled) return;
        setJalaseItems(menu.items.filter((entry) => entry.code !== "minutes").map((entry) => ({ to: `/meetings?output_type=${encodeURIComponent(entry.code)}`, label: entry.label, icon: meetingsIcon })));
      })
      .catch(() => { if (!cancelled) setJalaseItems([]); });
    return () => { cancelled = true; };
  }, [session]);
  const groups = NAVIGATION.map((group) => ({
    ...group,
    items: group.items.flatMap((item) => (item.to === "/meetings" ? [item, ...jalaseItems] : [item]))
      .filter((item) => !(operator && item.hideForOperator) && (!item.orgAdminOnly || orgAdmin) && canVisitPanel(session, item.to.split("?")[0])),
  })).filter((group) => group.items.length > 0);
  // A group with a single item (the dashboard) is shown as a plain link, outside the accordion.
  const accordionGroups = groups.filter((group) => group.items.length > 1);
  const activeGroup = accordionGroups.find((group) => group.items.some((item) => { const path = item.to.split("?")[0]; return path === "/" ? location.pathname === "/" : location.pathname === path || location.pathname.startsWith(`${path}/`); }))?.label ?? null;
  // Call management is open by default; navigating also opens the group of the active route, and each group toggles on its own.
  const DEFAULT_OPEN_GROUP = "مدیریت تماس‌ها";
  const [openGroups, setOpenGroups] = useState<string[]>(() => Array.from(new Set([DEFAULT_OPEN_GROUP, ...(activeGroup ? [activeGroup] : [])])));
  useEffect(() => {
    if (activeGroup) setOpenGroups((current) => (current.includes(activeGroup) ? current : [...current, activeGroup]));
  }, [activeGroup]);
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
  // One shared highlight rectangle that glides between menu items on hover/focus.
  const navRef = useRef<HTMLElement>(null);
  const lastTickItem = useRef<HTMLElement | null>(null);
  const [sound, setSound] = useState(getMenuSound);
  const soundOn = sound !== "off";
  const [pill, setPill] = useState<SidebarPill | null>(null);
  const movePill = (target: EventTarget | null) => {
    const nav = navRef.current;
    const item = target instanceof Element ? target.closest<HTMLElement>(".sidebar-nav-item") : null;
    if (!nav || !item || !nav.contains(item)) return;
    const navRect = nav.getBoundingClientRect();
    const rect = item.getBoundingClientRect();
    if (lastTickItem.current !== item) {
      lastTickItem.current = item;
      playMenuTick(Array.from(nav.querySelectorAll(".sidebar-nav-item")).indexOf(item));
    }
    setPill((current) => ({
      top: rect.top - navRect.top - nav.clientTop + nav.scrollTop,
      left: rect.left - navRect.left - nav.clientLeft + nav.scrollLeft,
      width: rect.width,
      height: rect.height,
      visible: true,
      snap: !current?.visible,
    }));
  };
  // A second pill marks the active route and glides to the new item on navigation.
  const [activePill, setActivePill] = useState<SidebarPill | null>(null);
  useLayoutEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const measure = (snap = false) => {
      const item = nav.querySelector<HTMLElement>('.sidebar-nav-item[aria-current="page"]');
      if (!item || item.closest('[data-open="false"]')) {
        setActivePill((current) => (current ? { ...current, visible: false } : current));
        return;
      }
      const navRect = nav.getBoundingClientRect();
      const rect = item.getBoundingClientRect();
      const next = { top: rect.top - navRect.top - nav.clientTop + nav.scrollTop, left: rect.left - navRect.left - nav.clientLeft + nav.scrollLeft, width: rect.width, height: rect.height };
      setActivePill((current) =>
        current && current.visible && current.top === next.top && current.left === next.left && current.width === next.width && current.height === next.height
          ? current
          : { ...next, visible: true, snap: snap || !current?.visible },
      );
    };
    measure();
    // While the sidebar width or an accordion panel animates, follow the layout frame by frame.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => measure(true));
    observer?.observe(nav);
    nav.querySelectorAll(".sidebar-group-panel").forEach((panel) => observer?.observe(panel));
    return () => observer?.disconnect();
  }, [location.pathname, collapsed, openGroups]);
  const hidePill = () => {
    lastTickItem.current = null;
    setPill((current) => (current ? { ...current, visible: false } : current));
  };
  useEffect(() => {
    setTooltip(null);
    setPill(null);
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
  const { mode, setMode } = useTheme();
  const THEME_OPTIONS: { value: ThemeMode; icon: IconifyIcon; label: string }[] = [
    { value: "light", icon: sunIcon, label: "روشن" },
    { value: "dark", icon: moonIcon, label: "تاریک" },
    { value: "system", icon: monitorIcon, label: "سیستم" },
  ];
  const themeIndex = THEME_OPTIONS.findIndex((option) => option.value === mode);
  const themeOption = THEME_OPTIONS[themeIndex] ?? THEME_OPTIONS[0];
  const nextThemeOption = THEME_OPTIONS[(themeIndex + 1) % THEME_OPTIONS.length];

  return (
    <>
    <div className="panel-sidebar flex h-full flex-col overflow-hidden text-white">
      <div className={`relative flex shrink-0 items-center border-b border-white/10 ${collapsed ? "flex-col justify-center gap-2 px-2 py-3" : "h-[96px] justify-start px-5"}`}>
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
        <button
          type="button"
          className={`sb-round p-2 text-[#F2F0EF] transition hover:bg-white/15 ${collapsed ? "order-first" : "absolute left-[3.5rem]"}`}
          aria-label={`صدای منو: ${menuSoundLabel(sound)} (برای تغییر کلیک کنید)`}
          title={`صدای منو: ${menuSoundLabel(sound)}`}
          onClick={() => { const next = nextMenuSound(sound); setMenuSound(next); setSound(next); playMenuTick(); }}
          onPointerEnter={showPointerTooltip(collapsed ? `صدا: ${menuSoundLabel(sound)}` : undefined)}
          onFocus={showFocusTooltip(collapsed ? `صدا: ${menuSoundLabel(sound)}` : undefined)}
          onPointerLeave={hideTooltip}
          onBlur={hideTooltip}
        >
          <Icon icon={soundOn ? volumeOnIcon : volumeOffIcon} className="h-5 w-5" aria-hidden="true" />
        </button>
        {closeMenu && (
          <button type="button" className="sb-round absolute left-4 p-2 text-[#F2F0EF] transition hover:bg-white/15" onClick={closeMenu} aria-label="بستن منو">
            <MenuIcon close />
          </button>
        )}
      </div>

      <nav
        ref={navRef}
        className={`sidebar-scroll relative flex-1 overflow-y-auto py-4 ${collapsed ? "px-2" : "px-3"}`}
        aria-label="منوی اصلی"
        onPointerOver={(event) => { if (event.pointerType !== "touch") movePill(event.target); }}
        onPointerLeave={hidePill}
        onFocus={(event) => { if ((event.target as HTMLElement).matches(":focus-visible")) movePill(event.target); }}
        onBlur={hidePill}
      >
        <span
          aria-hidden="true"
          className={`sidebar-active-pill sb-round${activePill?.visible ? " is-visible" : ""}${activePill?.snap ? " is-snap" : ""}`}
          style={activePill ? { top: activePill.top, left: activePill.left, width: activePill.width, height: activePill.height } : undefined}
        />
        <span
          aria-hidden="true"
          className={`sidebar-hover-pill sb-round${pill?.visible ? " is-visible" : ""}${pill?.snap ? " is-snap" : ""}`}
          style={pill ? { top: pill.top, left: pill.left, width: pill.width, height: pill.height } : undefined}
        />
        {groups.map((group, index) => {
          const items = group.items;
          // Minimal (icon-only) mode has no headers, so every group stays visible.
          const standalone = group.items.length === 1;
          const isOpen = collapsed || standalone || openGroups.includes(group.label);
          const panelId = `sidebar-group-${index}`;
          return (
            <div className={collapsed ? "mb-4 border-b border-white/10 pb-4 last:border-b-0" : standalone ? "mb-3 mt-1" : "mb-1"} key={group.label}>
              {!collapsed && !standalone && (
                <button
                  type="button"
                  className="sidebar-group-toggle flex w-full items-center justify-between px-3 py-2.5 text-[14px] font-semibold text-[#D5D0AE]/90 transition-colors hover:text-white"
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  onClick={() => { hidePill(); setOpenGroups((current) => (current.includes(group.label) ? current.filter((name) => name !== group.label) : [...current, group.label])); }}
                >
                  <span>{group.label}</span>
                  <Icon icon={chevronDownIcon} className="sidebar-group-chevron h-4 w-4" aria-hidden="true" />
                </button>
              )}
              <div id={panelId} className="sidebar-group-panel" data-open={isOpen}>
              <div className="sidebar-group-inner">
              <div className="space-y-0.5 pb-1">
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    data-tour-target={item.to}
                    onPointerEnter={showPointerTooltip(item.label)}
                    onFocus={showFocusTooltip(item.label)}
                    onPointerLeave={hideTooltip}
                    onBlur={hideTooltip}
                    onClick={() => { hideTooltip(); closeMenu?.(); }}
                    aria-label={collapsed ? item.label : undefined}
                    className={({ isActive: pathActive }) => { const isActive = navItemActive(item.to, pathActive, location.search); return `sidebar-nav-item sb-round group relative flex items-center ${collapsed ? "justify-center px-0" : "gap-3 px-3"} py-2.5 text-sm transition-colors duration-200 ${isActive ? "is-active font-bold text-white" : "text-[#F2F0EF]/85"}`; }}
                  >
                    {({ isActive: pathActive }) => { const isActive = navItemActive(item.to, pathActive, location.search); return (
                      <>
                        <Icon icon={item.icon} className={`h-5 w-5 shrink-0 ${isActive ? "text-[#E3E8B9]" : "text-[#F2F0EF]/65 transition group-hover:text-white"}`} aria-hidden="true" />
                        {!collapsed && <span className="truncate">{item.label}</span>}
                      </>
                    ); }}
                  </NavLink>
                ))}
              </div>
              </div>
              </div>
            </div>
          );
        })}
      </nav>

      <div className="shrink-0 border-t border-white/10 p-3">
        <div data-tour-target="role-badge" className={`sb-round flex items-center bg-black/10 text-[#F2F0EF] ${collapsed ? "flex-col gap-2 p-1.5" : "gap-3 p-2.5"}`} onPointerEnter={showPointerTooltip(roleLabel)} onPointerLeave={hideTooltip}>
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
        <div className={`mt-2 flex items-center ${collapsed ? "flex-col gap-2" : "justify-between gap-2"}`}>
          {collapsed ? (
            <button
              type="button"
              className="sb-round p-2 text-[#F2F0EF]/80 transition hover:bg-white/15 hover:text-white"
              aria-label={`ظاهر برنامه: ${themeOption.label} (برای تغییر کلیک کنید)`}
              title={`ظاهر برنامه: ${themeOption.label}`}
              onClick={() => { hideTooltip(); setMode(nextThemeOption.value); }}
              onPointerEnter={showPointerTooltip(`ظاهر: ${themeOption.label}`)}
              onFocus={showFocusTooltip(`ظاهر: ${themeOption.label}`)}
              onPointerLeave={hideTooltip}
              onBlur={hideTooltip}
            >
              <Icon icon={themeOption.icon} className="h-5 w-5" aria-hidden="true" />
            </button>
          ) : (
            <div role="radiogroup" aria-label="ظاهر برنامه" className="sb-round flex items-center bg-black/10">
              {THEME_OPTIONS.map((option) => {
                const active = option.value === mode;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    aria-label={option.label}
                    className={`sb-round p-2 transition ${active ? "bg-white/20 text-white" : "text-[#F2F0EF]/70 hover:bg-white/15 hover:text-white"}`}
                    onClick={() => { hideTooltip(); setMode(option.value); }}
                  >
                    <Icon icon={option.icon} className="h-4 w-4" aria-hidden="true" />
                  </button>
                );
              })}
            </div>
          )}
          {onReplayGuide && (operator || orgAdmin) && (
            <button
              type="button"
              data-tour-target="replay-help"
              className="sb-round p-2 text-[#F2F0EF]/80 transition hover:bg-white/15 hover:text-white"
              aria-label="نمایش دوباره تور راهنما"
              title="تور راهنما"
              onClick={() => { hideTooltip(); onReplayGuide(); }}
              onPointerEnter={showPointerTooltip(collapsed ? "تور راهنما" : undefined)}
              onFocus={showFocusTooltip(collapsed ? "تور راهنما" : undefined)}
              onPointerLeave={hideTooltip}
              onBlur={hideTooltip}
            >
              <Icon icon={circleHelpIcon} className="h-5 w-5" aria-hidden="true" />
            </button>
          )}
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
  const { session } = useAuth();
  const orgAdmin = isOrgAdmin(session?.role);

  // The sidebar walkthrough: starts once per session for a role that has not completed it, and can always be replayed.
  const tourRole = session && (isOrgAdmin(session.role) || isOperator(session.role)) ? session.role : null;
  const [tourActive, setTourActive] = useState(false);
  const tourAutoStartedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!session || !tourRole || tourAutoStartedFor.current === session.userId) return;
    tourAutoStartedFor.current = session.userId;
    if (hasCompletedTour(tourRole, window.localStorage)) return;
    const frame = window.requestAnimationFrame(() => setTourActive(true));
    return () => window.cancelAnimationFrame(frame);
  }, [session, tourRole]);
  useEffect(() => setMenuOpen(tourActive), [tourActive]);
  const replayGuide = tourRole ? () => setTourActive(true) : undefined;

  const desktopCollapsed = isAssistantPage ? !assistantExpanded : tourActive ? false : sidebarCollapsed;
  const toggleSidebarCollapsed = () => {
    setSidebarCollapsed((collapsed) => {
      writeSidebarCollapsed(!collapsed);
      return !collapsed;
    });
  };
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
        <aside id="client-desktop-menu" className={`fixed inset-y-0 right-0 z-40 hidden ${desktopCollapsed ? "w-20" : "w-72"} transition-[width] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] lg:block`}><Sidebar collapsed={desktopCollapsed} onToggleCollapse={isAssistantPage ? () => setAssistantExpanded((expanded) => !expanded) : toggleSidebarCollapsed} onReplayGuide={replayGuide} /></aside>

      <div className={`fixed inset-0 z-50 lg:hidden ${menuOpen ? "pointer-events-auto" : "pointer-events-none"}`} aria-hidden={!menuOpen}>
        <button type="button" className={`absolute inset-0 bg-slate-950/60 backdrop-blur-sm transition-opacity duration-300 ${menuOpen ? "opacity-100" : "opacity-0"}`} onClick={() => setMenuOpen(false)} aria-label="بستن منو" tabIndex={menuOpen ? 0 : -1} />
        <aside id="client-mobile-menu" className={`absolute inset-y-0 right-0 w-[min(88vw,19rem)] shadow-2xl transition-transform duration-300 ease-out ${menuOpen ? "visible translate-x-0" : "invisible translate-x-full"}`} role="dialog" aria-modal="true" aria-label="منوی کاربری">
          <Sidebar closeMenu={() => setMenuOpen(false)} onReplayGuide={replayGuide} />
        </aside>
      </div>

      <GuideTour active={tourActive} role={tourRole ?? ""} onFinish={() => setTourActive(false)} />

      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-canvas/90 backdrop-blur-xl lg:hidden">
        <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
          <button type="button" className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-canvas text-slate-700 shadow-sm transition hover:border-brand-200 hover:bg-brand-50 hover:text-brand-600" onClick={() => setMenuOpen(true)} aria-expanded={menuOpen} aria-controls="client-mobile-menu" aria-label="نمایش منو">
            <MenuIcon />
          </button>
          <h1 className="truncate text-base font-bold text-slate-900">{pageTitle}</h1>
        </div>
      </header>

        <main className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7 lg:px-8 lg:py-8">{orgAdmin && !isAssistantPage && location.pathname !== "/account" ? <BillingBanner /> : null}{orgAdmin && hasPanelAccess(session, "pbx_servers") && !isAssistantPage ? <ModuleUpdateBanner /> : null}{children}</main>
        {!isAssistantPage && hasPanelAccess(session, "assistant") ? <QuickAssistantWidget /> : null}
      </div>
    </>
  );
}
