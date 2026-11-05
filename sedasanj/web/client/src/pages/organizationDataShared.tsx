import { Icon, type IconifyIcon } from "@iconify/react";
import type { ReactNode } from "react";
import { fmt } from "../api";
import "./organization-data.css";

export const API = "/v1/account/data";
export const ORGANIZATION_DATA_PATH = "/account-settings?tab=data";
export const ORGANIZATION_DATA_HISTORY_PATH = "/account-settings/data/history";

export const KINDS = { manual: "بک‌آپ دستی", scheduled: "بک‌آپ زمان‌بندی‌شده", import: "بازیابی" };
export const STATES: Record<string, string> = {
  uploading: "در انتظار فایل", queued: "در صف", running: "در حال اجرا", review: "آمادهٔ بررسی",
  succeeded: "آماده", failed: "ناموفق", expired: "منقضی",
};
export const ERRORS: Record<string, string> = {
  org_archive_invalid: "فایل اصلی و کلید همان بک‌آپ را دوباره بررسی کنید.",
  org_archive_too_large: "حجم فایل از سقف مجاز بیشتر است.",
  org_archive_unavailable: "فضای ذخیره‌سازی و تنظیمات سامانه را بررسی کنید.",
  org_archive_review_changed: "مقصد تغییر کرده است. پیش‌نمایش جدید را بررسی کنید.",
  org_archive_mapping: "اعضای مقصد تغییر کرده‌اند. نگاشت را دوباره انتخاب کنید.",
  org_backup_destination: "میزبان، مسیر و نوع اتصال را بررسی کنید.",
  org_backup_ftp_failed: "مسیر، مجوز نوشتن و گواهی مقصد را بررسی کنید.",
  forbidden: "دسترسی مدیر سازمان را بررسی کنید.",
};

type Kind = keyof typeof KINDS;
type Count = { new: number; duplicate: number; skipped: number };
type Owner = { id: string; label: string; fallback: number; target: string; explicit: boolean };
export type Run = {
  id: string; kind: Kind; phase: string; state: string; transfer_state: string | null;
  transfer_attempts: number; next_attempt_at: string | null; error_code: string | null;
  size_bytes: number | null; checksum: string | null; created_at: string; expires_at: string;
  can_review: boolean; can_upload: boolean; can_download: boolean;
  summary: { counts?: Record<string, Count | number>; owners?: Owner[]; omitted?: Record<string, number> };
};

export function fileSize(bytes: number) {
  const units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت"];
  const power = Math.min(3, Math.max(0, Math.floor(Math.log(Math.max(1, bytes)) / Math.log(1024))));
  return `${fmt.decimal(bytes / 1024 ** power, 1)} ${units[power]}`;
}

export function Card({ title, icon, children }: { title: string; icon: IconifyIcon; children: ReactNode }) {
  return <section className="org-data-card">
    <h2 className="org-data-heading"><Icon icon={icon} aria-hidden="true" />{title}</h2>
    {children}
  </section>;
}

export function State({ value }: { value: string }) {
  return <span className={`org-data-status org-data-status--${value}`}>{STATES[value] ?? value}</span>;
}
