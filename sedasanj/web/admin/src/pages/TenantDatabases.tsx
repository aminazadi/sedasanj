import { useEffect, useState } from "react";
import { request } from "../api";
import { ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Page, TenantDatabaseStatus } from "../types";

export default function TenantDatabases() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<TenantDatabaseStatus> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

  async function load() {
    try {
      setPage(await request<Page<TenantDatabaseStatus>>(`/v1/admin/tenant-databases?offset=${offset}&limit=${limit}`));
      setError(null);
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(timer);
  }, [offset]);

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

  if (!page) return error ? <ErrorBox message={error} /> : <Loading />;
  const rows = page.items;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">دیتابیس سازمان‌ها</h1>
        <p className="mt-1 text-sm text-slate-500">وضعیت ساخت، انتقال و cutover خودکار هر سازمان</p>
      </div>
      <ErrorBox message={error} />
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
                </td>
                <td className="max-w-xs whitespace-normal text-xs text-rose-700">{row.migration_error || "—"}</td>
                <td className="space-y-1">
                  <button className="btn-ghost" disabled={retrying === row.tenant_id} onClick={() => void retry(row.tenant_id)}>تلاش مجدد</button>
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
