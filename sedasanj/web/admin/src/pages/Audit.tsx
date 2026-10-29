import { useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import type { AuditEvent, Page } from "../types";
import FilterBar from "@cbi/web-shared/components/FilterBar";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";

const COLUMNS: SkeletonColumn[] = [
  { label: "زمان", width: "8.5rem" },
  { label: "عامل", width: "4rem" },
  { label: "عملیات", width: "8rem", dir: "ltr" },
  { label: "مشتری", width: "10rem", dir: "ltr", cellClassName: "max-w-[12rem] truncate" },
  { label: "جزئیات", width: "16rem", dir: "ltr", cellClassName: "max-w-sm truncate text-xs text-slate-500" },
];

export default function Audit() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState("");
  const audit = useResource<Page<AuditEvent>>((signal) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (action) params.set("action", action);
    return request<Page<AuditEvent>>(`/v1/admin/audit?${params.toString()}`, { signal });
  }, [action, offset]);
  const page = audit.data;
  const events = page?.items ?? null;

  return (
    <div className="space-y-4">
      <ErrorBox message={audit.error} />
      <FilterBar
        hasActive={Boolean(action)}
        onClear={() => { setAction(""); setOffset(0); }}
        fields={[
          { id: "action", label: "عملیات", active: Boolean(action), onRemove: () => { setAction(""); setOffset(0); }, className: "sm:w-64", control: <input className="input" dir="ltr" placeholder="tenant.suspend" value={action} onChange={(event) => { setAction(event.target.value); setOffset(0); }} /> },
        ]}
      />

      <div className="card">
        {audit.loading ? (
          <SkeletonTable columns={COLUMNS} rows={events?.length ? Math.min(events.length, limit) : 10} />
        ) : !events || events.length === 0 ? (
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
