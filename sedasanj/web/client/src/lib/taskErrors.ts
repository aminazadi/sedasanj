import { ApiError } from "../api";

export function taskErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "task_version_conflict") return "این کار تغییر کرده است؛ نسخه تازه را دریافت و تغییرات خود را دوباره ثبت کنید.";
    if (error.code === "task_assignee_invalid") return "مسئول انتخاب‌شده دسترسی جاری به تماس ندارد؛ نسخه تازه را دریافت و فرد دیگری انتخاب کنید.";
    if (error.code === "not_found" || error.code === "forbidden") return "به این کار یا تماس دسترسی ندارید؛ به فهرست برگردید و مورد مجاز دیگری انتخاب کنید.";
    if (error.code === "invalid_request") return "اطلاعات معتبر نیست؛ عنوان، موعد و تماس انتخاب‌شده را بررسی و دوباره تلاش کنید.";
  }
  return "عملیات انجام نشد؛ اتصال و دسترسی را بررسی و دوباره تلاش کنید.";
}
