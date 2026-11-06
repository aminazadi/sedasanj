import { ApiError } from "../api";

const MESSAGES: Record<string, string> = {
  apk_invalid:
    "فایل APK پذیرفته نشد: باید APK کامل release با شناسه app.jalasenegar.jalase_negar و امضای رسمی باشد. APK رسمی را دوباره بسازید و بارگذاری کنید.",
  apk_inspection_unavailable:
    "بررسی APK روی سرور ممکن نیست. از مدیر سرور بخواهید aapt2 و apksigner را نصب و JALASE_NEGAR_APK_CERT_SHA256 را تنظیم کند، سپس دوباره تلاش کنید.",
  release_version_conflict:
    "شماره ساخت (versionCode) باید از همه نسخه‌های منتشرشده و لغوشده بیشتر باشد و نسخه تکراری نیست. در pubspec.yaml عدد بعد از + را بالا ببرید و APK را دوباره بسازید.",
  release_file_unavailable:
    "فایل APK در ذخیره‌سازی در دسترس نیست. چند دقیقه بعد دوباره تلاش کنید؛ اگر ادامه داشت پیش‌نویس را حذف و فایل را دوباره بارگذاری کنید.",
  archive_too_large: "حجم APK از سقف مجاز (۲۰۰ مگابایت) بیشتر است. حجم برنامه را کم کنید و دوباره بارگذاری کنید.",
  forbidden: "فقط مدیر ارشد می‌تواند نسخه‌ها را تغییر دهد.",
  unauthorized: "رمز عبور یا کد دومرحله‌ای درست نیست.",
};

/** Persian message that names the next action for a release API failure. */
export function releaseErrorMessage(error: unknown): string {
  // The API uses one `unauthorized` code for a wrong password/2FA code and for an expired
  // login. Only the first is about the password; an upload never asks for one.
  if (error instanceof ApiError && error.code === "unauthorized" && !/password|two-factor/i.test(error.message)) {
    return "نشست ورود شما منقضی شده است. صفحه را باز کنید، دوباره وارد پنل شوید و APK را بارگذاری کنید.";
  }
  if (error instanceof ApiError && MESSAGES[error.code]) return MESSAGES[error.code];
  if (error instanceof Error && /[؀-ۿ]/.test(error.message)) return error.message;
  return "درخواست انجام نشد. اتصال را بررسی کنید و دوباره تلاش کنید.";
}
