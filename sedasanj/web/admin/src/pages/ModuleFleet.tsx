import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { ModuleInstallation, ModuleInstallationStats, Page } from "../types";

interface DiagnosticReport {
  id: string;
  module_version: string;
  ok: boolean;
  failed_checks: number;
  created_at: string;
  report: {
    checks?: Array<{ id: string; status: "ok" | "warn" | "fail"; code: string; detail: string }>;
    recent_codes?: Record<string, number>;
    queue?: Record<string, number>;
  };
}

const UPDATE_STATUS: Record<NonNullable<ModuleInstallation["last_update_status"]>, { label: string; className: string }> = {
  started: { label: "در حال اجرا", className: "bg-sky-50 text-sky-700" },
  succeeded: { label: "موفق", className: "bg-emerald-50 text-emerald-700" },
  failed: { label: "ناموفق", className: "bg-rose-50 text-rose-700" },
  rolled_back: { label: "بازگردانی شد", className: "bg-amber-50 text-amber-800" },
};

const STALE_MS = 7 * 24 * 3600 * 1000;

export default function ModuleFleet() {
  const limit = 50;
  const [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const outdatedOnly = params.get("outdated") === "true";
  const product = params.get("product") === "issabel-recuploader" ? "issabel-recuploader" : "freepbx-recuploader";
  const setOffset = (value: number) => setParams((old) => { const next = new URLSearchParams(old); next.set("offset", String(value)); return next; });
  const setOutdatedOnly = (value: boolean) => setParams((old) => { const next = new URLSearchParams(old); next.set("outdated", String(value)); next.delete("offset"); return next; });
  const [page, setPage] = useState<Page<ModuleInstallation> | null>(null);
  const [stats, setStats] = useState<ModuleInstallationStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [diag, setDiag] = useState<{ item: ModuleInstallation; reports: DiagnosticReport[] } | null>(null);

  async function openDiagnostics(item: ModuleInstallation) {
    try {
      const reports = await request<DiagnosticReport[]>(`/v1/admin/module-installations/${item.id}/diagnostics`);
      setDiag({ item, reports });
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const reload = useCallback(async () => {
    try {
      const query = new URLSearchParams({ offset: String(offset), limit: String(limit), product });
      if (outdatedOnly) query.set("outdated", "true");
      const [list, summary] = await Promise.all([
        request<Page<ModuleInstallation>>(`/v1/admin/module-installations?${query}`),
        request<ModuleInstallationStats>(`/v1/admin/module-installations/stats?product=${product}`),
      ]);
      setPage(list);
      setStats(summary);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [offset, outdatedOnly, product]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const max = Math.max(1, ...(stats?.versions.map((item) => item.count) ?? [1]));

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />
      <div className="flex items-center justify-between">
        <Link to="/module-releases" className="text-sm text-slate-500 hover:text-slate-800">→ نسخه‌های ماژول</Link>
      </div>

      <div className="card">
        <h2 className="mb-3 font-bold text-slate-900">توزیع نسخه‌ها</h2>
        {!stats ? (
          <Loading />
        ) : stats.versions.length === 0 ? (
          <Empty>هنوز هیچ سروری چک به‌روزرسانی انجام نداده است.</Empty>
        ) : (
          <div className="space-y-2">
            {stats.versions.map((item) => (
              <div key={item.version} className="flex items-center gap-3 text-sm">
                <span className="w-20 shrink-0 font-mono" dir="ltr">v{item.version}</span>
                <div className="h-5 flex-1 overflow-hidden rounded bg-slate-100">
                  <div
                    className={`h-full ${item.version === stats.latest_version ? "bg-brand-500" : "bg-slate-400"}`}
                    style={{ width: `${(item.count / max) * 100}%` }}
                  />
                </div>
                <span className="w-12 shrink-0 text-left">{fmt.int(item.count)}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-bold text-slate-900">سرورهای تلفنی</h2>
          <select className="input" aria-label="نوع مرکز تلفن" value={product} onChange={(event) => setParams({ product: event.target.value })}>
            <option value="freepbx-recuploader">FreePBX</option><option value="issabel-recuploader">ایزابل</option>
          </select>
          <label className="flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={outdatedOnly}
              onChange={(event) => {
                setOutdatedOnly(event.target.checked);

              }}
            />
            فقط سرورهای قدیمی
          </label>
        </div>
        {!page ? (
          <Loading />
        ) : page.items.length === 0 ? (
          <Empty />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>سازمان</th>
                  <th>میزبان</th>
                  <th>نسخهٔ ماژول</th>
                  <th>FreePBX / PHP</th>
                  <th>سرویس</th>
                  <th>آخرین بازدید</th>
                  <th>آخرین به‌روزرسانی</th>
                  <th>سلامت</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => {
                  const stale = Date.now() - new Date(item.last_seen_at).getTime() > STALE_MS;
                  const update = item.last_update_status ? UPDATE_STATUS[item.last_update_status] : null;
                  return (
                    <tr key={item.id}>
                      <td>
                        <Link className="hover:underline" to={`/tenants/${item.tenant_id}`}>{item.tenant_name ?? "—"}</Link>
                      </td>
                      <td className="font-mono text-xs" dir="ltr">{item.hostname ?? item.host_uuid.slice(0, 8)}</td>
                      <td>
                        <span className="font-mono" dir="ltr">v{item.module_version}</span>
                        {item.update_available ? (
                          <span className="badge mr-1 bg-amber-50 text-amber-800" dir="ltr">→ v{item.latest_version}</span>
                        ) : (
                          <span className="badge mr-1 bg-emerald-50 text-emerald-700">به‌روز</span>
                        )}
                      </td>
                      <td className="text-xs" dir="ltr">{item.product === "issabel-recuploader" ? `Issabel ${item.issabel_version ?? "?"}` : item.freepbx_version ?? "?"} / {item.php_version ?? "?"}</td>
                      <td>{item.service_status === "running" ? "فعال" : item.service_status === "stopped" ? "متوقف" : item.service_status ?? "—"}</td>
                      <td className={stale ? "text-rose-700" : ""}>{fmt.dateTime(item.last_seen_at)}</td>
                      <td>
                        {update ? (
                          <span className={`badge ${update.className}`} title={item.last_update_error ?? undefined}>{update.label}</span>
                        ) : "—"}
                        {item.last_update_error ? (
                          <div className="mt-1 max-w-xs truncate text-xs text-rose-700" title={item.last_update_error}>{item.last_update_error}</div>
                        ) : null}
                      </td>
                      <td>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => void openDiagnostics(item)}>
                          گزارش سلامت
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
      </div>
      {diag ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-3xl rounded-xl bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-lg font-bold" dir="ltr">{diag.item.hostname ?? diag.item.host_uuid}</h2>
              <button type="button" className="btn btn-ghost" onClick={() => setDiag(null)}>بستن</button>
            </div>
            {diag.reports.length === 0 ? (
              <p className="text-sm text-slate-500">هنوز گزارشی ارسال نشده است. ماژول نسخهٔ ۱٫۴ به بالا هر ساعت گزارش می‌فرستد.</p>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-slate-600">
                  آخرین گزارش: {fmt.dateTime(diag.reports[0].created_at)} — {diag.reports[0].ok ? "همه‌چیز سالم" : `${diag.reports[0].failed_checks} مورد نیازمند اقدام`}
                </p>
                <table className="table">
                  <thead><tr><th>مورد</th><th>وضعیت</th><th>توضیح</th></tr></thead>
                  <tbody>
                    {(diag.reports[0].report.checks ?? []).filter((c) => c.status !== "ok").map((c) => (
                      <tr key={c.id}>
                        <td dir="ltr" className="text-xs">{c.id}</td>
                        <td>{c.status === "fail" ? "خطا" : "هشدار"}</td>
                        <td className="text-sm">
                          {c.detail}{" "}
                          {c.code ? <a className="underline" dir="ltr" href={`/help/errors/${encodeURIComponent(c.code)}`} target="_blank" rel="noreferrer">[{c.code}]</a> : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {Object.keys(diag.reports[0].report.recent_codes ?? {}).length > 0 ? (
                  <p className="text-xs text-slate-500" dir="ltr">
                    {Object.entries(diag.reports[0].report.recent_codes ?? {}).map(([code, n]) => `${code} ×${n}`).join("  ")}
                  </p>
                ) : null}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
