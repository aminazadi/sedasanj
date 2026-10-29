import HelpMediaLibrary from "../components/HelpMediaLibrary";

export default function HelpMediaPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-extrabold text-slate-900">تصویر و ویدئو</h1>
        <p className="text-sm text-slate-500">
          فایل‌های آپلودشده برای مقاله‌های راهنما. فایلی که در یک مقاله استفاده شده باشد حذف نمی‌شود.
        </p>
      </div>
      <HelpMediaLibrary />
    </div>
  );
}
