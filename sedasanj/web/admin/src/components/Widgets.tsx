import type { ReactNode } from "react";
import { Icon } from "@iconify/react";
import alarmClockIcon from "@iconify/icons-fluent-emoji/alarm-clock";
import calendarIcon from "@iconify/icons-fluent-emoji/calendar";
import clipboardIcon from "@iconify/icons-fluent-emoji/clipboard";
import moneyBagIcon from "@iconify/icons-fluent-emoji/money-bag";
import officeBuildingIcon from "@iconify/icons-fluent-emoji/office-building";
import purseIcon from "@iconify/icons-fluent-emoji/purse";
import shoppingCartIcon from "@iconify/icons-fluent-emoji/shopping-cart";
import stopwatchIcon from "@iconify/icons-fluent-emoji/stopwatch";
import telephoneIcon from "@iconify/icons-fluent-emoji/telephone";
import warningIcon from "@iconify/icons-fluent-emoji/warning";
import { fmt } from "../api";

export function Stat({ title, value, tone }: { title: string; value: string; tone?: string }) {
  const icon = title.includes("مشتری")
    ? officeBuildingIcon
    : title.includes("تماس")
      ? telephoneIcon
      : title.includes("دقیقه")
        ? stopwatchIcon
        : title === "اعتبار"
          ? purseIcon
          : title.includes("درآمد")
            ? moneyBagIcon
            : title.includes("سفارش")
            ? shoppingCartIcon
            : title.includes("پرداخت")
              ? warningIcon
              : title.includes("تمدید")
                ? calendarIcon
                : title.includes("کار")
                  ? clipboardIcon
                  : alarmClockIcon;
  return (
    <div className="panel-stat-card card">
      <div className="relative z-10 mb-3 flex items-start justify-between gap-3">
        <div className="text-sm font-medium text-slate-600">{title}</div>
        <span className="flex h-14 w-14 shrink-0 items-center justify-center" aria-hidden="true">
          <Icon icon={icon} className="h-14 w-14" />
        </span>
      </div>
      <div className={`relative z-10 text-2xl font-extrabold tracking-tight ${tone ?? "text-slate-900"}`}>{value}</div>
    </div>
  );
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
      {message}
    </div>
  );
}

export function Loading() {
  return <div className="py-10 text-center text-slate-400">در حال بارگذاری…</div>;
}

export function Empty({ children = "موردی یافت نشد." }: { children?: ReactNode }) {
  return <div className="py-10 text-center text-slate-400">{children}</div>;
}

export function Pagination({
  offset,
  limit,
  total,
  loading = false,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  loading?: boolean;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <nav className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4" aria-label="صفحه‌بندی">
      <span className="text-xs text-slate-500">
        صفحه {fmt.int(page)} از {fmt.int(pages)} · {fmt.int(total)} مورد
      </span>
      <div className="flex gap-2">
        <button className="btn-ghost text-sm" type="button" disabled={loading || offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>صفحه قبل</button>
        <button className="btn-ghost text-sm" type="button" disabled={loading || offset + limit >= total} onClick={() => onChange(offset + limit)}>صفحه بعد</button>
      </div>
    </nav>
  );
}
