import type { ReactNode } from "react";

export type IconName = "arrow" | "back" | "brain" | "chart" | "check" | "chevron" | "clock" | "copy" | "download" | "headset" | "layers" | "lock" | "login" | "key" | "menu" | "message" | "phone" | "play" | "pulse" | "quote" | "refresh" | "search" | "send" | "shield" | "spark" | "target" | "tasks" | "trend" | "userPlus" | "users" | "x";

const paths: Record<IconName, ReactNode> = {
  arrow: <><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></>,
  back: <><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></>,
  brain: <><path d="M9.5 4A2.5 2.5 0 0 0 7 6.5v.2A3.5 3.5 0 0 0 5.5 13v.5A3.5 3.5 0 0 0 9 17h1V5.5A1.5 1.5 0 0 0 8.5 4Z"/><path d="M14.5 4A2.5 2.5 0 0 1 17 6.5v.2a3.5 3.5 0 0 1 1.5 6.3v.5A3.5 3.5 0 0 1 15 17h-1V5.5A1.5 1.5 0 0 1 15.5 4Z"/><path d="M7 9.5h3M14 9.5h3M7.5 14H10M14 14h2.5M10 20v-3M14 20v-3"/></>,
  chart: <><path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 3-4 3 2 5-7"/><path d="M16 6h2v2"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  chevron: <path d="m15 18-6-6 6-6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  copy: <><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></>,
  download: <><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 21h16"/></>,
  headset: <><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><path d="M18 19c0 1.1-.9 2-2 2h-3"/><rect x="3" y="13" width="4" height="6" rx="2"/><rect x="17" y="13" width="4" height="6" rx="2"/></>,
  layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></>,
  login: <><path d="M9 21H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/></>,
  key: <><circle cx="8" cy="15" r="4"/><path d="m11 12 9-9"/><path d="m16 7 3 3"/></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16"/></>,
  message: <><path d="M21 12a8 8 0 0 1-8 8H6l-3 2 1-5a9 9 0 1 1 17-5Z"/><path d="M8 12h.01M12 12h.01M16 12h.01"/></>,
  phone: <path d="M6.6 2.8 9 8l-2.1 1.8a15.8 15.8 0 0 0 7.3 7.3L16 15l5.2 2.4c.5.2.8.8.6 1.3l-.8 2.2c-.2.7-.9 1.1-1.6 1.1A17.4 17.4 0 0 1 2 4.6c0-.7.4-1.4 1.1-1.6l2.2-.8c.5-.2 1.1.1 1.3.6Z"/>,
  play: <path d="M7 4.5v15l12-7.5-12-7.5Z"/>,
  pulse: <path d="M3 12h4l2-7 4 14 2-7h6"/>,
  quote: <><path d="M9 11H5a4 4 0 0 0 4 4V8a4 4 0 0 0-4 4"/><path d="M19 11h-4a4 4 0 0 0 4 4V8a4 4 0 0 0-4 4"/></>,
  refresh: <><path d="M20 12a8 8 0 1 1-2.5-5.8"/><path d="M20 4v5h-5"/></>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  send: <><path d="m21 3-9.5 18-2.5-7.5L1.5 11 21 3Z"/><path d="M21 3 9 13.5"/></>,
  shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></>,
  spark: <><path d="m12 3 1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2L12 3Z"/><path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14ZM5 13l.7 1.8 1.8.7-1.8.7L5 18l-.7-1.8-1.8-.7 1.8-.7L5 13Z"/></>,
  target: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></>,
  tasks: <><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 3.5h6M8.5 9l1.5 1.5L13 7.5M8.5 15l1.5 1.5 3-3M15 9h1M15 15h1"/></>,
  trend: <><path d="m3 17 6-6 4 4 7-8"/><path d="M15 7h5v5"/></>,
  userPlus: <><path d="M15 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><path d="M19 8v6M16 11h6"/></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/></>,
  x: <><path d="m6 6 12 12M18 6 6 18"/></>,
};

export function Icon({ name, size = 24, className }: { name: IconName; size?: number; className?: string }) {
  return <svg aria-hidden="true" focusable="false" className={className} viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}
