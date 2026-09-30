import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { AuditEvent, Page } from "../types";

export default function Audit() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<AuditEvent> | null>(null);
  const [action, setAction] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (action) params.set("action", action);
    setPage(null);
    request<Page<AuditEvent>>(`/v1/admin/audit?${params.toString()}`)
      .then(setPage)
      .catch((err) => setError(err.message));
  }, [action, offset]);
  const events = page?.items ?? null;

  return (
    <div className="space-y-4">
      <ErrorBox message={error} />
      <div className="card flex gap-3">
        <div className="flex-1">
          <label className="label">فیلتر عملیات</label>
          <input
            className="input"
            dir="ltr"
            placeholder="tenant.suspend"
            value={action}
            onChange={(event) => { setAction(event.target.value); setOffset(0); }}
          />
        </div>
      </div>

      <div className="card">
        {!events ? (
          <Loading />
        ) : events.length === 0 ? (
          <Empty />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>زمان</th>
                <th>عامل</th>
                <th>عملیات</th>
                <th>مشتری</th>
                <th>جزئیات</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>{fmt.dateTime(event.created_at)}</td>
                  <td>{event.actor_type}</td>
                  <td dir="ltr">{event.action}</td>
                  <td dir="ltr" className="max-w-[12rem] truncate">
                    {event.tenant_id ? fmt.digits(event.tenant_id) : "—"}
                  </td>
                  <td dir="ltr" className="max-w-sm truncate text-xs text-slate-500">
                    {fmt.digits(JSON.stringify(event.payload))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
    </div>
  );
}
