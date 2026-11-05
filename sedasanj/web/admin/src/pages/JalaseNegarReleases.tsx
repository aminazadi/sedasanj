import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, fmt, request, tokens } from "../api";
import { useSensitiveAction } from "../components/SensitiveActionDialog";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import { releaseErrorMessage } from "../lib/jalaseNegarErrors";
import { useTablePageSize } from "../lib/useTablePagination";
import { formatBytes } from "../sanitize";
import type { JalaseNegarRelease, JalaseNegarReleasePage, JalaseNegarReleaseStatus } from "../types";

export const STATUS_META: Record<JalaseNegarReleaseStatus, { label: string; className: string }> = {
  draft: { label: "پیش‌نویس", className: "bg-slate-100 text-slate-600" },
  published: { label: "منتشرشده", className: "bg-emerald-50 text-emerald-700" },
  revoked: { label: "لغوشده", className: "bg-rose-50 text-rose-700" },
};

const FILTERS: Array<{ value: JalaseNegarReleaseStatus | ""; label: string }> = [
  { value: "", label: "همه" },
  { value: "published", label: "منتشرشده" },
  { value: "draft", label: "پیش‌نویس" },
  { value: "revoked", label: "لغوشده" },
];

export async function downloadApk(release: JalaseNegarRelease): Promise<void> {
  const response = await fetch(`/v1/admin/jalase-negar/releases/${release.id}/download`, {
    headers: { Authorization: `Bearer ${tokens.access() ?? ""}` },
  });
  if (!response.ok) throw new ApiError(response.status, "download", "دانلود فایل ناموفق بود. چند دقیقه بعد دوباره تلاش کنید.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `jalase-negar-${release.version_name}.apk`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function JalaseNegarReleases() {
  const [limit] = useTablePageSize();
  const [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const rawFilter = params.get("status") ?? "";
  const filter = (rawFilter in STATUS_META ? rawFilter : "") as JalaseNegarReleaseStatus | "";
  const setOffset = (value: number) =>
    setParams((old) => { const next = new URLSearchParams(old); next.set("offset", String(value)); return next; });
  const setFilter = (value: string) =>
    setParams((old) => {
      const next = new URLSearchParams(old);
      if (value) next.set("status", value); else next.delete("status");
      next.delete("offset");
      return next;
    });
  const [page, setPage] = useState<JalaseNegarReleasePage | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [askProof, proofDialog] = useSensitiveAction();

  const reload = useCallback(async () => {
    try {
      const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (filter) query.set("status", filter);
      setPage(await request<JalaseNegarReleasePage>(`/v1/admin/jalase-negar/releases?${query}`));
      setError(null);
    } catch (err) {
      setError(releaseErrorMessage(err));
    }
  }, [limit, offset, filter]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function act(release: JalaseNegarRelease, action: "publish" | "revoke" | "delete") {
    const prompts = {
      publish: `نسخهٔ ${release.version_name} منتشر شود؟ اپ‌های نصب‌شده در اجرای بعدی آن را پیشنهاد می‌دهند.`,
      revoke: `انتشار نسخهٔ ${release.version_name} لغو شود؟ پیشنهاد و دانلود آن فوراً متوقف می‌شود. دستگاه‌هایی که آن را نصب کرده‌اند نسخهٔ اصلاحی با شماره ساخت بالاتر می‌خواهند.`,
      delete: `پیش‌نویس ${release.version_name} و فایل آن برای همیشه حذف شود؟`,
    };
    let proof = null;
    if (action === "delete") {
      if (!window.confirm(prompts[action])) return;
    } else {
      proof = await askProof(prompts[action]);
      if (!proof) return;
    }
    setBusy(release.id);
    try {
      if (action === "delete") {
        await request(`/v1/admin/jalase-negar/releases/${release.id}`, { method: "DELETE" });
      } else {
        await request(`/v1/admin/jalase-negar/releases/${release.id}/${action}`, { method: "POST", body: proof });
      }
      await reload();
    } catch (err) {
      setError(releaseErrorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      {proofDialog}
      <ErrorBox message={error} />

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="card">
          <div className="text-sm text-slate-500">آخرین شماره ساخت منتشرشده</div>
          <div className="mt-1 text-2xl font-extrabold text-slate-900" dir="ltr">
            {page?.latest_published_code ?? "—"}
          </div>
        </div>
        <div className="card text-sm text-slate-600">
          پیش از انتشار عمومی، APK واقعی توزیع‌شده باید با همان کلید امضای رسمی ساخته شده باشد؛ در غیر این‌صورت اندروید نصب روی نسخه‌های فعلی را بدون پاک کردن اطلاعات نمی‌پذیرد.
        </div>
      </div>

      <div className="card">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((item) => (
              <button
                key={item.value}
                className={`rounded-lg px-3 py-1.5 text-sm ${filter === item.value ? "bg-brand-500 text-white" : "text-slate-600 hover:bg-slate-100"}`}
                onClick={() => setFilter(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <Link className="btn text-sm" to="/jalase-negar-releases/new">ثبت نسخهٔ جدید</Link>
        </div>

        {!page ? (
          <Loading />
        ) : page.items.length === 0 ? (
          <Empty>هنوز نسخه‌ای ثبت نشده است.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>نسخه</th>
                  <th>شماره ساخت</th>
                  <th>عنوان</th>
                  <th>وضعیت</th>
                  <th>انتشار</th>
                  <th>تاریخ انتشار</th>
                  <th>حجم</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {page.items.map((release) => (
                  <tr key={release.id}>
                    <td className="font-mono font-bold" dir="ltr">v{release.version_name}</td>
                    <td className="font-mono" dir="ltr">{release.version_code}</td>
                    <td className="max-w-xs truncate">{release.title}</td>
                    <td><span className={`badge ${STATUS_META[release.status].className}`}>{STATUS_META[release.status].label}</span></td>
                    <td className="whitespace-nowrap text-xs" dir="ltr">
                      {release.rollout_percent}% · {release.channel}
                      {release.min_supported_version_code > 0 ? ` · min ${release.min_supported_version_code}` : ""}
                    </td>
                    <td>{release.published_at ? fmt.dateTime(release.published_at) : "—"}</td>
                    <td>{formatBytes(release.artifact_size)}</td>
                    <td className="whitespace-nowrap">
                      <Link className="btn-ghost text-xs" to={`/jalase-negar-releases/${release.id}`}>ویرایش</Link>{" "}
                      {release.status === "draft" ? (
                        <>
                          <button className="btn-ghost text-xs" disabled={busy === release.id} onClick={() => act(release, "publish")}>انتشار</button>{" "}
                          <button className="btn-ghost text-xs text-rose-700" disabled={busy === release.id} onClick={() => act(release, "delete")}>حذف</button>
                        </>
                      ) : release.status === "published" ? (
                        <button className="btn-ghost text-xs text-rose-700" disabled={busy === release.id} onClick={() => act(release, "revoke")}>لغو انتشار</button>
                      ) : null}{" "}
                      <button className="btn-ghost text-xs" onClick={() => downloadApk(release).catch((err) => setError(releaseErrorMessage(err)))}>دانلود</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
      </div>
    </div>
  );
}
