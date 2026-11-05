import { ApiError } from "../api";

const MESSAGES: Record<string, string> = {
  ml_model_not_found: "این مدل دیگر وجود ندارد؛ شاید نسخهٔ جدیدتر جایگزین آن شده است. فهرست را تازه کنید.",
  ml_model_invalid: "این کار برای وضعیت فعلی مدل ممکن نیست. فهرست را تازه کنید؛ برای حذف، ابتدا مدل را باطل کنید.",
  ml_model_checksum_mismatch: "SHA-256 فایل با مقدار اعلام‌شده نمی‌خواند. فایل را دوباره بفرستید.",
  ml_model_version_conflict: "این نسخه با محتوای دیگری ثبت شده است. شمارهٔ نسخه را افزایش دهید.",
  release_file_unavailable: "فایل مدل در ذخیره‌سازی در دسترس نیست. چند دقیقه بعد دوباره تلاش کنید.",
  forbidden: "فقط مدیر ارشد می‌تواند این عملیات را انجام دهد.",
  unauthorized: "رمز عبور یا کد دومرحله‌ای درست نیست.",
};

/** Persian message that names the next action for a model registry API failure. */
export function modelErrorMessage(error: unknown): string {
  if (error instanceof ApiError && MESSAGES[error.code]) return MESSAGES[error.code];
  if (error instanceof Error && /[؀-ۿ]/.test(error.message)) return error.message;
  return "درخواست انجام نشد. اتصال را بررسی کنید و دوباره تلاش کنید.";
}
