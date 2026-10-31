import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import ReleaseTimeline, { SeverityBadge } from "@cbi/web-shared/components/ReleaseTimeline";
import { ApiError, fmt, request, tokens } from "../api";
import { useSensitiveAction } from "../components/SensitiveActionDialog";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import { formatBytes, sanitizeHtml } from "../sanitize";
import type { ModuleInstallationStats, ModuleRelease, ModuleReleaseStatus, Page } from "../types";

const STATUS_META: Record<ModuleReleaseStatus, { label: string; className: string }> = {
  draft: { label: "پیش‌نویس", className: "bg-slate-100 text-slate-600" },
  published: { label: "منتشرشده", className: "bg-emerald-50 text-emerald-700" },
  revoked: { label: "لغوشده", className: "bg-rose-50 text-rose-700" },
};

const FILTERS: Array<{ value: ModuleReleaseStatus | ""; label: string }> = [
  { value: "", label: "همه" },
  { value: "published", label: "منتشرشده" },
  { value: "draft", label: "پیش‌نویس" },
  { value: "revoked", label: "لغوشده" },
];

export async function downloadRelease(release: ModuleRelease): Promise<void> {
  const response = await fetch(`/v1/admin/module-releases/${release.id}/download`, {
    headers: { Authorization: `Bearer ${tokens.access() ?? ""}` },
  });
  if (!response.ok) throw new ApiError(response.status, "download", "دانلود فایل ناموفق بود.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = release.product === "issabel-recuploader" ? `recuploader-${release.version}.tgz` : `asterisk-module-${release.version}.zip`;
  link.click();
  URL.revokeObjectURL(url);
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-extrabold text-slate-900" dir="auto">{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-500">{hint}</div> : null}
    </div>
  );
}

export default function ModuleReleases() {
  const limit = 25;
  const [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const filter = (params.get("status") || "") as ModuleReleaseStatus | "";
  const product = params.get("product") === "issabel-recuploader" ? "issabel-recuploader" : "freepbx-recuploader";
  const setOffset = (value: number) => setParams((old) => { const next = new URLSearchParams(old); next.set("offset", String(value)); return next; });
  const setFilter = (value: string) => setParams((old) => { const next = new URLSearchParams(old); next.set("status", value); next.delete("offset"); return next; });
  const [page, setPage] = useState<Page<ModuleRelease> | null>(null);
  const [stats, setStats] = useState<ModuleInstallationStats | null>(null);
  const [published, setPublished] = useState<ModuleRelease[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [askProof, proofDialog] = useSensitiveAction();

  const reload = useCallback(async () => {
    try {
      const query = new URLSearchParams({ offset: String(offset), limit: String(limit), product });
      if (filter) query.set("status", filter);
      const [list, fleet, live] = await Promise.all([
        request<Page<ModuleRelease>>(`/v1/admin/module-releases?${query}`),
        request<ModuleInstallationStats>(`/v1/admin/module-installations/stats?product=${product}`),
        request<Page<ModuleRelease>>(`/v1/admin/module-releases?status=published&limit=100&product=${product}`),
      ]);
      setPage(list);
      setStats(fleet);
      setPublished(live.items);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [offset, filter, product]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function act(release: ModuleRelease, action: "publish" | "revoke" | "delete") {
    const prompts = {
      publish: `نسخهٔ ${release.version} منتشر شود؟ همهٔ سرورهای تلفنی در بارگذاری بعدی صفحه آن را می‌بینند.`,
      revoke: `انتشار نسخهٔ ${release.version} لغو شود؟ سرورها دیگر این نسخه را دریافت نمی‌کنند.`,
      delete: `پیش‌نویس ${release.version} و فایل آن برای همیشه حذف شود؟`,
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
        await request(`/v1/admin/module-releases/${release.id}`, { method: "DELETE" });
      } else {
        await request(`/v1/admin/module-releases/${release.id}/${action}`, { method: "POST", body: proof });
      }
      await reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const latest = stats?.latest_version ?? null;
  const onLatest = latest ? stats?.versions.find((item) => item.version === latest)?.count ?? 0 : 0;
  const adoption = stats && stats.total > 0 ? Math.round((onLatest / stats.total) * 100) : 0;

  return (
    <div className="space-y-4">
      {proofDialog}
      <ErrorBox message={error} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="آخرین نسخهٔ منتشرشده" value={latest ? `v${latest}` : "—"} />
        <StatCard label="سرورهای فعال" value={fmt.int(stats?.total ?? 0)} />
        <StatCard
          label="روی آخرین نسخه"
          value={`${fmt.digits(adoption)}٪`}
          hint={`${fmt.int(onLatest)} از ${fmt.int(stats?.total ?? 0)} سرور`}
        />
        <StatCard
          label="به‌روزرسانی ناموفق"
          value={fmt.int(stats?.failed_updates ?? 0)}
          hint={stats?.failed_updates ? "جزئیات در صفحهٔ سرورها" : undefined}
        />
      </div>

      <div className="card">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1">
            <select className="input" aria-label="نوع مرکز تلفن" value={product} onChange={(event) => setParams({ product: event.target.value })}>
              <option value="freepbx-recuploader">FreePBX</option><option value="issabel-recuploader">ایزابل</option>
            </select>
            {FILTERS.map((item) => (
              <button
                key={item.value}
                className={`rounded-lg px-3 py-1.5 text-sm ${filter === item.value ? "bg-brand-500 text-white" : "text-slate-600 hover:bg-slate-100"}`}
                onClick={() => {
                  setFilter(item.value);

                }}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Link className="btn-ghost text-sm" to="/module-fleet">سرورهای تلفنی</Link>
            <Link className="btn text-sm" to="/module-releases/new">ثبت نسخهٔ جدید</Link>
          </div>
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
                  <th>عنوان</th>
                  <th>اهمیت</th>
                  <th>وضعیت</th>
                  <th>تاریخ انتشار</th>
                  <th>سرورها</th>
                  <th>حجم</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {page.items.map((release) => (
                  <tr key={release.id}>
                    <td className="font-mono font-bold" dir="ltr">
                      v{release.version}
                      {release.channel === "beta" ? <span className="badge mr-1 bg-violet-50 text-violet-700">beta</span> : null}
                    </td>
                    <td className="max-w-xs truncate">{release.title}</td>
                    <td><SeverityBadge severity={release.severity} /></td>
                    <td><span className={`badge ${STATUS_META[release.status].className}`}>{STATUS_META[release.status].label}</span></td>
                    <td>{release.published_at ? fmt.dateTime(release.published_at) : "—"}</td>
                    <td>{fmt.int(release.installations)}</td>
                    <td>{formatBytes(release.artifact_size)}</td>
                    <td className="whitespace-nowrap">
                      <Link className="btn-ghost text-xs" to={`/module-releases/${release.id}`}>ویرایش</Link>{" "}
                      {release.status === "draft" ? (
                        <>
                          <button className="btn-ghost text-xs" disabled={busy === release.id} onClick={() => act(release, "publish")}>انتشار</button>{" "}
                          <button className="btn-ghost text-xs text-rose-700" disabled={busy === release.id} onClick={() => act(release, "delete")}>حذف</button>
                        </>
                      ) : release.status === "published" ? (
                        <button className="btn-ghost text-xs text-rose-700" disabled={busy === release.id} onClick={() => act(release, "revoke")}>لغو انتشار</button>
                      ) : null}{" "}
                      <button className="btn-ghost text-xs" onClick={() => downloadRelease(release).catch((err) => setError(err.message))}>دانلود</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
      </div>

      <div className="card">
        <h2 className="mb-1 text-lg font-bold text-slate-900">تاریخچهٔ نسخه‌ها</h2>
        <p className="mb-4 text-sm text-slate-500">همان چیزی که مدیران سازمان و صفحهٔ ماژول FreePBX می‌بینند.</p>
        <ReleaseTimeline
          sanitize={sanitizeHtml}
          entries={published.map((release) => ({
            id: release.id,
            version: release.version,
            title: release.title,
            severity: release.severity,
            html: release.changelog_html,
            published_at: release.published_at,
          }))}
        />
      </div>
    </div>
  );
}
