import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, request, uploadWithProgress } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";
import { formatBytes } from "../sanitize";

const LINKS = "/v1/admin/jalase-negar/store-links";
const BUILDS = "/v1/admin/jalase-negar/desktop-builds";

const STORES: Array<[keyof StoreLinks, string]> = [
  ["bazaar", "کافه‌بازار"], ["myket", "مایکت"], ["google_play", "گوگل‌پلی"],
  ["app_store", "اپ‌استور"], ["anardoni", "اناردونی"], ["sibapp", "سیب‌اپ"],
];
const PLATFORMS = { windows: "ویندوز", macos: "مک" } as const;

type StoreLinks = { bazaar: string; myket: string; google_play: string; app_store: string; anardoni: string; sibapp: string };
type Build = { id: string; platform: keyof typeof PLATFORMS; version_name: string; file_name: string; artifact_sha256: string; artifact_size: number; created_at: string };

const message = (reason: unknown) =>
  reason instanceof ApiError && reason.code === "invalid_request"
    ? "مقادیر واردشده معتبر نیست. لینک‌ها باید با https شروع شوند؛ پسوند فایل (ویندوز: exe، msi، zip — مک: dmg، pkg، zip) و شمارهٔ نسخه را بررسی و دوباره تلاش کنید."
    : reason instanceof ApiError && reason.code === "archive_too_large"
      ? "فایل از حد مجاز بزرگ‌تر است. نسخهٔ کوچک‌تری بسازید و دوباره بارگذاری کنید."
      : reason instanceof ApiError
        ? reason.message
        : "ارتباط با سامانه برقرار نشد. اتصال را بررسی و دوباره تلاش کنید.";

export default function JalaseNegarDownloads() {
  const [links, setLinks] = useState<StoreLinks | null>(null);
  const [builds, setBuilds] = useState<Build[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [platform, setPlatform] = useState<keyof typeof PLATFORMS>("windows");
  const [version, setVersion] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);

  const reload = useCallback(async () => {
    try {
      const [l, b] = await Promise.all([request<StoreLinks>(LINKS), request<{ items: Build[] }>(BUILDS)]);
      setLinks(l);
      setBuilds(b.items);
    } catch (reason) {
      setError(message(reason));
    }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  async function saveLinks(event: FormEvent) {
    event.preventDefault();
    if (!links || busy) return;
    setBusy(true); setError(null); setNotice("");
    try {
      setLinks(await request<StoreLinks>(LINKS, { method: "PUT", body: links }));
      setNotice("لینک فروشگاه‌ها ذخیره شد.");
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || !version.trim() || progress !== null) return;
    const form = new FormData();
    form.append("platform", platform);
    form.append("version", version.trim());
    form.append("file", file);
    setError(null); setNotice(""); setProgress(0);
    try {
      await uploadWithProgress<Build>(BUILDS, form, setProgress);
      setFile(null); setVersion("");
      setNotice("فایل بارگذاری شد و در پنجرهٔ دانلود صفحهٔ اصلی نمایش داده می‌شود.");
      await reload();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setProgress(null);
    }
  }

  async function remove(build: Build) {
    if (!window.confirm(`فایل ${build.file_name} برای همیشه حذف شود؟`)) return;
    try {
      await request<void>(`${BUILDS}/${build.id}`, { method: "DELETE" });
      await reload();
    } catch (reason) {
      setError(message(reason));
    }
  }

  if (!links) return error ? <ErrorBox message={error} /> : <Loading />;
  const latest = new Set(
    (["windows", "macos"] as const).map((p) => builds.find((b) => b.platform === p)?.id).filter(Boolean),
  );

  return <div className="space-y-5">
    <ErrorBox message={error} />
    {notice && <p className="text-sm text-emerald-700" role="status">{notice}</p>}
    <form className="card space-y-4" onSubmit={saveLinks}>
      <div>
        <h1 className="text-lg font-bold">دانلود جلسه‌نگار: لینک فروشگاه‌ها</h1>
        <p className="mt-1 text-sm text-slate-500">با زدن دکمهٔ دانلود در صفحهٔ اصلی، پنجره‌ای با همهٔ این لینک‌ها باز می‌شود. فروشگاهی که لینکش خالی باشد نمایش داده نمی‌شود. اگر فقط نسخهٔ اندروید در دسترس باشد، دکمه مستقیم دانلود را شروع می‌کند.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {STORES.map(([key, label]) => <label key={key} className="block text-sm">
          <span className="mb-1 block font-medium">{label}</span>
          <input className="input" dir="ltr" type="url" placeholder="https://" maxLength={2048} value={links[key]} onChange={(e) => setLinks({ ...links, [key]: e.target.value })}/>
        </label>)}
      </div>
      <button className="btn-primary" disabled={busy}>{busy ? "در حال ذخیره…" : "ذخیره لینک‌ها"}</button>
    </form>

    <form className="card space-y-4" onSubmit={upload}>
      <div>
        <h2 className="text-lg font-bold">بارگذاری نسخهٔ ویندوز و مک</h2>
        <p className="mt-1 text-sm text-slate-500">جدیدترین فایل هر پلتفرم در پنجرهٔ دانلود نمایش داده می‌شود. ویندوز: exe، msi یا zip. مک: dmg، pkg یا zip.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <label className="block text-sm"><span className="mb-1 block font-medium">پلتفرم</span>
          <select className="input" value={platform} onChange={(e) => setPlatform(e.target.value as keyof typeof PLATFORMS)}>
            {Object.entries(PLATFORMS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
        <label className="block text-sm"><span className="mb-1 block font-medium">شمارهٔ نسخه</span>
          <input className="input" dir="ltr" placeholder="1.2.0" maxLength={32} value={version} onChange={(e) => setVersion(e.target.value)}/></label>
        <label className="block text-sm"><span className="mb-1 block font-medium">فایل نصب</span>
          <input className="input" type="file" accept=".exe,.msi,.dmg,.pkg,.zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)}/></label>
      </div>
      {progress !== null && <progress className="w-full" value={progress} max={1} aria-label="پیشرفت بارگذاری"/>}
      <button className="btn-primary" disabled={!file || !version.trim() || progress !== null}>{progress !== null ? "در حال بارگذاری…" : "بارگذاری"}</button>
    </form>

    <div className="card overflow-x-auto">
      <h2 className="mb-3 text-lg font-bold">فایل‌های بارگذاری‌شده</h2>
      {builds.length === 0 ? <p className="text-sm text-slate-500">هنوز فایلی بارگذاری نشده است.</p> : <table className="w-full text-sm">
        <thead><tr className="text-start text-slate-500"><th className="p-2 text-start">پلتفرم</th><th className="p-2 text-start">نسخه</th><th className="p-2 text-start">حجم</th><th className="p-2 text-start">SHA-256</th><th className="p-2"/></tr></thead>
        <tbody>{builds.map((b) => <tr key={b.id} className="border-t">
          <td className="p-2">{PLATFORMS[b.platform]}{latest.has(b.id) && <span className="ms-2 rounded bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">فعال</span>}</td>
          <td className="p-2" dir="ltr">{b.version_name}</td>
          <td className="p-2">{formatBytes(b.artifact_size)}</td>
          <td className="p-2 font-mono text-xs" dir="ltr">{b.artifact_sha256.slice(0, 16)}…</td>
          <td className="p-2"><button type="button" className="text-rose-700" onClick={() => void remove(b)}>حذف</button></td>
        </tr>)}</tbody>
      </table>}
    </div>
  </div>;
}
