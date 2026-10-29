import type { ReactNode } from "react";
import { Skeleton, SkeletonPanel } from "@cbi/web-shared/components/Skeleton";
import { Icon } from "@iconify/react";
import { EMPTY_STATE_ART } from "./pageArt";
import alarmClockIcon from "@iconify-icons/lucide/alarm-clock";
import buildingIcon from "@iconify-icons/lucide/building-2";
import calendarIcon from "@iconify-icons/lucide/calendar";
import clipboardIcon from "@iconify-icons/lucide/clipboard-list";
import creditCardIcon from "@iconify-icons/lucide/credit-card";
import revenueIcon from "@iconify-icons/lucide/circle-dollar-sign";
import shoppingCartIcon from "@iconify-icons/lucide/shopping-cart";
import stopwatchIcon from "@iconify-icons/lucide/timer";
import telephoneIcon from "@iconify-icons/lucide/phone";
import warningIcon from "@iconify-icons/lucide/triangle-alert";
import { fmt } from "../api";

export function Stat({ title, value, tone }: { title: string; value: string; tone?: string }) {
  const icon = title.includes("مشتری")
    ? buildingIcon
    : title.includes("تماس")
      ? telephoneIcon
      : title.includes("دقیقه")
        ? stopwatchIcon
        : title === "اعتبار"
          ? creditCardIcon
          : title.includes("درآمد")
            ? revenueIcon
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
          <Icon icon={icon} className="h-9 w-9 text-[#4B6E48]" />
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

/** Generic placeholder for pages without their own skeleton. */
export function Loading() {
  return <SkeletonPanel />;
}

/** Layout-shaped placeholder shown while the session is restored on a hard refresh. */
export function AdminShellSkeleton() {
  return (
    <div className="panel-shell min-h-screen lg:pr-72">
      <aside className="fixed inset-y-0 right-0 z-40 hidden w-72 lg:block">
        <div className="panel-sidebar flex h-full flex-col overflow-hidden">
          <div className="flex h-[96px] shrink-0 items-center justify-center border-b border-[color:var(--line)] px-5"><Skeleton style={{ width: "9rem", height: "2.5rem" }} /></div>
          <div className="space-y-3 p-4">{Array.from({ length: 10 }, (_, index) => <Skeleton key={index} style={{ width: "100%", height: "2.5rem" }} />)}</div>
        </div>
      </aside>
      <main className="admin-main mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6 sm:py-7 lg:px-8 lg:py-8">
        <span className="sr-only" role="status">در حال بارگذاری</span>
        <div className="space-y-4" aria-hidden="true">
          <Skeleton style={{ width: "100%", height: "5rem" }} />
          <SkeletonPanel rows={5} />
        </div>
      </main>
    </div>
  );
}

export function Empty({ children = "موردی یافت نشد." }: { children?: ReactNode }) {
  return <div className="panel-empty text-slate-400"><img className="panel-empty__art" src={EMPTY_STATE_ART} alt="" aria-hidden="true" loading="lazy" decoding="async" /><span>{children}</span></div>;
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
