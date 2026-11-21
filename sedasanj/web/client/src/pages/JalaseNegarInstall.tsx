import { Icon } from "@iconify/react";
import downloadIcon from "@iconify-icons/lucide/download";
import externalLinkIcon from "@iconify-icons/lucide/external-link";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";
import { PageHeader } from "../components/PageHeader";
import { useResource } from "@cbi/web-shared/lib/useResource";

type AppFile = { version: string; size: number; download_path: string };
type AppDownloads = { android: AppFile | null; windows: AppFile | null; macos: AppFile | null; stores: Record<string, string> };

const FILE_LABELS: Array<["android" | "windows" | "macos", string]> = [
  ["android", "اندروید (فایل APK)"], ["windows", "ویندوز"], ["macos", "مک"],
];
const STORE_LABELS: Array<[string, string]> = [
  ["bazaar", "کافه‌بازار"], ["myket", "مایکت"], ["google_play", "گوگل‌پلی"],
  ["app_store", "اپ‌استور"], ["anardoni", "اناردونی"], ["sibapp", "سیب‌اپ"],
];
const sizeLabel = (bytes: number) => `${fmt.int(Math.max(1, Math.round(bytes / (1024 * 1024))))} مگابایت`;

const INSTALL_STEPS = [
  "اپ جلسه‌نگار را از یکی از لینک‌های زیر روی گوشی یا رایانه نصب کنید.",
  "از تب «جلسه‌نگار» در تنظیمات حساب، کد اتصال بسازید.",
  "کد را در اپ جلسه‌نگار اسکن کنید یا فایل پیکربندی را در آن باز کنید.",
  "جلسه را ضبط کنید؛ پس از پایان، صورت‌جلسه و خروجی‌های آن در پنل زیر گروه «جلسه‌نگار» قابل مشاهده است.",
];

export default function JalaseNegarInstall() {
  const downloads = useResource<AppDownloads>((signal) => request<AppDownloads>("/v1/jalase-negar/downloads", { signal }), []);
  const data = downloads.data;
  const files = data ? FILE_LABELS.filter(([key]) => data[key]) : [];
  const stores = data ? STORE_LABELS.filter(([key]) => data.stores[key]) : [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="راهنمای نصب و دانلود جلسه‌نگار"
        description="اپ جلسه‌نگار را دانلود و نصب کنید و آن را به صداسنج وصل کنید تا جلسه‌های ضبط‌شده در این پنل رونویسی و تحلیل شوند."
        actions={<Link className="btn-ghost" to="/account-settings?tab=jalase">اتصال اپ جلسه‌نگار</Link>}
      />
      {downloads.error ? <ErrorBox message={downloads.error} /> : null}
      {!data && !downloads.error ? <Loading /> : null}
      {data ? (
        <>
          {files.length > 0 ? (
            <section className="card space-y-3">
              <h2 className="font-bold">دانلود مستقیم</h2>
              <ul className="space-y-2">
                {files.map(([key, label]) => { const file = data[key]!; return (
                  <li key={key} className="flex flex-wrap items-center justify-between gap-3 border border-[color:var(--line)] px-4 py-3">
                    <span className="flex items-center gap-2 font-medium"><Icon icon={downloadIcon} className="h-5 w-5" aria-hidden="true" />{label}</span>
                    <a className="btn-ghost" href={file.download_path} download>
                      <span dir="ltr" data-keep-latin-digits>v{file.version} · {sizeLabel(file.size)}</span>
                    </a>
                  </li>
                ); })}
              </ul>
            </section>
          ) : null}
          {stores.length > 0 ? (
            <section className="card space-y-3">
              <h2 className="font-bold">فروشگاه‌های اپلیکیشن</h2>
              <ul className="space-y-2">
                {stores.map(([key, label]) => (
                  <li key={key} className="flex flex-wrap items-center justify-between gap-3 border border-[color:var(--line)] px-4 py-3">
                    <span className="font-medium">{label}</span>
                    <a className="btn-ghost" href={data.stores[key]} target="_blank" rel="noopener noreferrer">
                      <span className="flex items-center gap-1">باز کردن<Icon icon={externalLinkIcon} className="h-4 w-4" aria-hidden="true" /></span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {files.length === 0 && stores.length === 0 ? <ErrorBox message="فعلاً فایل یا لینک دانلودی ثبت نشده است؛ کمی بعد دوباره سر بزنید." /> : null}
        </>
      ) : null}
      <section className="card">
        <h2 className="mb-3 font-bold">مراحل نصب و اتصال</h2>
        <ol className="list-decimal space-y-2 ps-6 text-sm leading-7">
          {INSTALL_STEPS.map((step, index) => <li key={index}>{step}</li>)}
        </ol>
      </section>
    </div>
  );
}
