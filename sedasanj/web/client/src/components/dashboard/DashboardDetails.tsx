import type { ReactNode } from "react";

/** Keep disclosure chrome separate so nested panels retain their shared card styles. */
export function DashboardDetails({ open, onToggle, children }: { open: boolean; onToggle: (open: boolean) => void; children: ReactNode }) {
  return <details className="dashboard-details min-w-0" open={open} onToggle={(event) => onToggle(event.currentTarget.open)}>
    <summary className="card dashboard-details__summary">
      <span className="font-bold text-brand-700">تحلیل‌های تکمیلی</span>
      <p className="mt-1 text-xs leading-6 text-slate-500">شاخص‌های CRM، کارها، تماس‌های بی‌پاسخ، تعادل گفت‌وگو، اعتراض‌ها و محصولات، جدول اپراتورها و کمپین‌ها و تماس‌های اخیر</p>
    </summary>
    {children}
  </details>;
}
