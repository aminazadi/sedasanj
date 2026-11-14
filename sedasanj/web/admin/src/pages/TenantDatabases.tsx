import { useTablePageSize } from "../lib/useTablePagination";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { request } from "../api";
import { ErrorBox, Loading, Pagination } from "../components/Widgets";
import { formatBytes } from "../sanitize";
import type { Page, TenantDatabaseStatus } from "../types";

type TenantDatabasePage = Page<TenantDatabaseStatus> & { backup_interval_hours: number | null };

type StorageUsage = {
  measured_at: string; audio_retention_days: number; audio_bytes: number; assistant_file_bytes: number;
  archive_bytes: number; pending_audio_cleanup_bytes: number; database_bytes: number | null;
  database_backup_bytes: number; duplicate_audio_candidate_bytes: number;
  largest_relations: { name: string; heap_bytes: number; index_bytes: number; toast_bytes: number }[];
  object_store: { objects: number; complete: boolean; bytes_by_category: Record<string, number> } | null;
};

const STORAGE_CATEGORIES: Record<string, string> = {
  media: "رسانه‌ها", assistant: "فایل‌های دستیار", archives: "آرشیوها", database_backups: "بک‌آپ دیتابیس",
};

export default function TenantDatabases() {
  const [limit] = useTablePageSize();
  const [searchParams, setSearchParams] = useSearchParams();
  const parsedOffset = Number.parseInt(searchParams.get("offset") || "0", 10);
  const offset = Number.isSafeInteger(parsedOffset) && parsedOffset >= 0 ? parsedOffset : 0;
  const [page, setPage] = useState<TenantDatabasePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const storageParam = searchParams.get("storage");
  const storageTenant = storageParam && /^[0-9a-f-]{36}$/i.test(storageParam) ? storageParam : null;
  const [storage, setStorage] = useState<{ tenantId: string; usage: StorageUsage } | null>(null);
  const [storageError, setStorageError] = useState<string | null>(null);
  const storageScan = searchParams.get("scan") === "1";
  const [storageRefresh, setStorageRefresh] = useState(0);
  const usage = storage?.tenantId === storageTenant ? storage.usage : null;

  async function load() {
    try {
      setPage(await request<TenantDatabasePage>(`/v1/admin/tenant-databases?offset=${offset}&limit=${limit}`));
      setError(null);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(timer);
  }, [limit, offset]);

  useEffect(() => {
    if (!storageTenant) return;
    let stopped = false;
    setStorageError(null);
    void request<StorageUsage>(`/v1/admin/tenants/${storageTenant}/storage?scan=${storageScan}`).then((value) => {
      if (!stopped) setStorage({ tenantId: storageTenant, usage: value });
    }).catch((reason: Error) => { if (!stopped) setStorageError(reason.message); });
    return () => { stopped = true; };
  }, [storageTenant, storageScan, storageRefresh]);

  function showStorage(tenantId: string | null) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("scan");
      if (tenantId) next.set("storage", tenantId);
      else next.delete("storage");
      return next;
    });
  }

  async function retry(tenantId: string) {
    setRetrying(tenantId);
    try {
      await request(`/v1/admin/tenants/${tenantId}/database-migration/retry`, {
        method: "POST",
      });
      await load();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setRetrying(null);
    }
  }

  async function retryAllFailed() {
    setRetrying("all");
    try {
      await request("/v1/admin/tenant-databases/retry-failed", { method: "POST" });
      await load();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setRetrying(null);
    }
  }

  async function requestBackup(tenantId: string) {
    setRetrying(tenantId);
    try {
      await request(`/v1/admin/tenants/${tenantId}/backup`, { method: "POST" });
      await load();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setRetrying(null);
    }
  }

  async function rollback(tenantId: string) {
    setRetrying(tenantId);
    try {
      await request(`/v1/admin/tenants/${tenantId}/database-migration/rollback`, {
        method: "POST",
      });
      await load();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setRetrying(null);
    }
  }

  function setOffset(nextOffset: number) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (nextOffset > 0) next.set("offset", String(nextOffset));
      else next.delete("offset");
      return next;
    });
  }

  if (!page) return error ? <ErrorBox message={error} /> : <Loading />;
  const rows = page.items;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">دیتابیس سازمان‌ها</h1>
        <p className="mt-1 text-sm text-slate-500">وضعیت ساخت، انتقال و cutover خودکار هر سازمان</p>
        {page.backup_interval_hours ? (
          <p className="mt-1 text-sm text-slate-500">
            دورهٔ بک‌آپ دیتابیس {page.backup_interval_hours.toLocaleString("fa-IR")} ساعت
          </p>
        ) : null}
      </div>
      <ErrorBox message={error} />
      {rows.some((row) => row.migration_status === "failed") ? (
        <button className="btn-ghost" type="button" disabled={retrying === "all"} onClick={() => void retryAllFailed()}>
          تلاش مجدد همهٔ ناموفق‌ها
        </button>
      ) : null}
      {storageTenant && <section className="card space-y-3" aria-label="گزارش فضای سازمان">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-bold">فضای سازمان {rows.find((row) => row.tenant_id === storageTenant)?.tenant_name}</h2>
          <button className="btn-ghost" type="button" onClick={() => showStorage(null)}>بستن گزارش</button>
        </div>
        <ErrorBox message={storageError} />
        {usage ? <>
          <dl className="grid gap-2 sm:grid-cols-3">
            <div><dt>صدای ثبت‌شده</dt><dd>{formatBytes(usage.audio_bytes)}</dd></div>
            <div><dt>فایل‌های دستیار</dt><dd>{formatBytes(usage.assistant_file_bytes)}</dd></div>
            <div><dt>بک‌آپ داده‌های سازمان</dt><dd>{formatBytes(usage.archive_bytes)}</dd></div>
            <div><dt>صدا در صف پاک‌سازی</dt><dd>{formatBytes(usage.pending_audio_cleanup_bytes)}</dd></div>
            <div><dt>بک‌آپ دیتابیس</dt><dd>{formatBytes(usage.database_backup_bytes)}</dd></div>
            <div><dt>حجم دیتابیس اختصاصی</dt><dd>{usage.database_bytes === null ? "—" : formatBytes(usage.database_bytes)}</dd></div>
            <div><dt>صدای احتمالاً تکراری</dt><dd>{formatBytes(usage.duplicate_audio_candidate_bytes)}</dd></div>
          </dl>
          {usage.largest_relations.length > 0 && <div className="overflow-x-auto">
            <table className="table">
              <thead><tr><th>بزرگ‌ترین جدول‌ها</th><th>جدول</th><th>ایندکس</th><th>TOAST</th></tr></thead>
              <tbody>{usage.largest_relations.map((row) => <tr key={row.name}>
                <td dir="ltr">{row.name}</td><td>{formatBytes(row.heap_bytes)}</td>
                <td>{formatBytes(row.index_bytes)}</td><td>{formatBytes(row.toast_bytes)}</td>
              </tr>)}</tbody>
            </table>
          </div>}
          <p className="text-sm text-slate-500">
            {new Date(usage.measured_at).toLocaleString("fa-IR")} · نگهداشت صوت {new Intl.NumberFormat("fa-IR").format(usage.audio_retention_days)} روز
          </p>
          {usage.object_store && <div className="space-y-2">
            <h3 className="font-bold">حجم فایل‌ها در استوریج</h3>
            {!usage.object_store.complete && <p>اندازه‌گیری به سقف ۱۰٬۰۰۰ فایل رسید. اعداد زیر فقط فایل‌های بررسی‌شده را پوشش می‌دهند.</p>}
            <dl className="grid gap-2 sm:grid-cols-4">{Object.entries(usage.object_store.bytes_by_category).map(([key, bytes]) =>
              <div key={key}><dt>{STORAGE_CATEGORIES[key] ?? key}</dt><dd>{formatBytes(bytes)}</dd></div>)}</dl>
          </div>}
          <button className="btn-ghost" type="button" onClick={() => {
            if (storageScan) setStorageRefresh((version) => version + 1);
            else setSearchParams((current) => {
              const next = new URLSearchParams(current);
              next.set("scan", "1");
              return next;
            });
          }}>اندازه‌گیری فایل‌های استوریج</button>
        </> : !storageError && <Loading />}
      </section>}
      <div className="card overflow-x-auto">
        <table className="table min-w-[900px]">
          <thead><tr><th>سازمان</th><th>دیتابیس</th><th>وضعیت</th><th>مرحله</th><th>نسخه</th><th>آخرین پشتیبان</th><th>خطا</th><th /></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.tenant_id}>
                <td>{row.tenant_name}</td>
                <td dir="ltr">{row.database_name || "Legacy"}</td>
                <td>{row.database_status} / {row.migration_status || "—"}</td>
                <td>{row.migration_phase || "—"}</td>
                <td dir="ltr">{row.schema_revision || "—"}</td>
                <td className="text-xs">
                  <div>{row.backup_status || "—"}</div>
                  <div dir="ltr">{row.backup_completed_at ? new Date(row.backup_completed_at).toLocaleString("fa-IR") : "—"}</div>
                  {row.backup_checksum ? <div dir="ltr" title={row.backup_checksum}>{row.backup_checksum.slice(0, 12)}…</div> : null}
                  {row.backup_id ? <div dir="ltr" className="break-all">{row.backup_id}</div> : null}
                  {row.backup_error_info ? (
                    <div className="mt-1 space-y-1 text-rose-700">
                      <div dir="ltr" className="font-mono">{row.backup_error_info.code}</div>
                      <div>{row.backup_error_info.message}</div>
                      <div className="text-slate-600">{row.backup_error_info.action}</div>
                      {row.backup_error_info.detail ? (
                        <details>
                          <summary className="cursor-pointer">جزئیات فنی</summary>
                          <div dir="ltr" className="mt-1 max-h-32 overflow-auto break-words text-left">{row.backup_error_info.detail}</div>
                        </details>
                      ) : null}
                    </div>
                  ) : null}
                  {row.backup_restore_verified_at ? (
                    <div>ریستور تأییدشده <bdi>{new Date(row.backup_restore_verified_at).toLocaleString("fa-IR")}</bdi></div>
                  ) : null}
                </td>
                <td className="max-w-xs whitespace-normal text-xs text-rose-700">
                  {row.migration_error_info ? (
                    <div className="space-y-1">
                      <div dir="ltr" className="font-mono">{row.migration_error_info.code}</div>
                      <div>{row.migration_error_info.message}</div>
                      <div className="text-slate-600">{row.migration_error_info.action}</div>
                      {row.migration_error ? (
                        <details>
                          <summary className="cursor-pointer">جزئیات فنی</summary>
                          <div dir="ltr" className="mt-1 max-h-32 overflow-auto break-words text-left">{row.migration_error}</div>
                        </details>
                      ) : null}
                    </div>
                  ) : "—"}
                </td>
                <td className="space-y-1">
                  <button className="btn-ghost" type="button" onClick={() => showStorage(row.tenant_id)}>مصرف فضا</button>
                  <button className="btn-ghost" disabled={retrying === row.tenant_id} onClick={() => void retry(row.tenant_id)}>تلاش مجدد</button>
                  {row.database_status === "ready" ? (
                    <button className="btn-ghost" disabled={retrying === row.tenant_id || row.backup_status === "requested" || row.backup_status === "running"} onClick={() => void requestBackup(row.tenant_id)}>پشتیبان‌گیری فوری</button>
                  ) : null}
                  {row.migration_status === "completed" && row.rollback_until && new Date(row.rollback_until) > new Date() ? (
                    <button className="btn-ghost text-rose-700" disabled={retrying === row.tenant_id} onClick={() => void rollback(row.tenant_id)}>بازگشت امن</button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} />
    </div>
  );
}
