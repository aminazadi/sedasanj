import { useState } from "react";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { fmt, query, request } from "../api";
import { Empty, ErrorBox } from "./Widgets";
import type { ContactPage, Page, PbxExtension, User } from "../types";

const COLUMNS: SkeletonColumn[] = [
  { label: "داخلی", width: "5rem", dir: "ltr" },
  { label: "نام در FreePBX", width: "9rem" },
  { label: "مخاطب دفترچه تلفن", width: "12rem" },
  { label: "اپراتور", width: "12rem" },
];

interface Options {
  contacts: ContactPage["items"];
  operators: User[];
}

/** Lists PBX extensions synced from the FreePBX module and links each to a contact/operator. */
export default function ExtensionsPanel({ canEdit }: { canEdit: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const extensions = useResource<PbxExtension[]>((signal) => request<PbxExtension[]>("/v1/extensions", { signal }), []);
  const options = useResource<Options>(async (signal) => {
    if (!canEdit) return { contacts: [], operators: [] };
    const [contacts, users] = await Promise.all([
      request<ContactPage>(`/v1/contacts${query({ limit: 100 })}`, { signal }),
      request<Page<User>>("/v1/auth/users?limit=100&offset=0", { signal }),
    ]);
    return { contacts: contacts.items, operators: users.items.filter((user) => user.role === "operator") };
  }, [canEdit]);

  async function assign(row: PbxExtension, field: "contact_id" | "user_id", value: string) {
    setBusyId(row.id);
    setError(null);
    try {
      await request<PbxExtension>(`/v1/extensions/${row.id}`, { method: "PATCH", body: { [field]: value || null } });
      extensions.reload({ silent: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "اختصاص داخلی انجام نشد؛ دوباره تلاش کنید.");
    } finally {
      setBusyId(null);
    }
  }

  const rows = extensions.data ?? [];
  const contactOptions = options.data?.contacts ?? [];
  const operatorOptions = options.data?.operators ?? [];

  return (
    <div className="card space-y-3">
      <div>
        <h2 className="font-bold">داخلی‌ها</h2>
        <p className="section-hint">
          داخلی‌ها از ماژول FreePBX (دکمهٔ «همگام‌سازی داخلی‌ها») می‌آیند. تماس بین دو داخلی «داخلی» ثبت می‌شود و نام مخاطب یا اپراتور کنار شمارهٔ داخلی نمایش داده می‌شود.
        </p>
      </div>
      <ErrorBox message={extensions.error ?? error} />
      {extensions.loading && !extensions.data ? (
        <SkeletonTable columns={COLUMNS} rows={4} />
      ) : rows.length === 0 ? (
        <Empty>هنوز داخلی‌ای همگام نشده؛ در صفحهٔ ماژول FreePBX دکمهٔ «Sync extensions» را بزنید.</Empty>
      ) : (
        <table className="table" dir="rtl">
          <thead>
            <tr>{COLUMNS.map((column, index) => <th key={index}>{column.label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td dir="ltr" className="font-bold">{fmt.digits(row.extension)}</td>
                <td>{row.pbx_name ?? "—"}</td>
                <td>
                  {canEdit ? (
                    <select className="input" aria-label={`مخاطب داخلی ${row.extension}`} value={row.contact_id ?? ""} disabled={busyId === row.id} onChange={(event) => void assign(row, "contact_id", event.target.value)}>
                      <option value="">بدون مخاطب</option>
                      {row.contact_id && !contactOptions.some((item) => item.id === row.contact_id) ? <option value={row.contact_id}>{row.contact_name}</option> : null}
                      {contactOptions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                  ) : (row.contact_name ?? "—")}
                </td>
                <td>
                  {canEdit ? (
                    <select className="input" aria-label={`اپراتور داخلی ${row.extension}`} value={row.user_id ?? ""} disabled={busyId === row.id} onChange={(event) => void assign(row, "user_id", event.target.value)}>
                      <option value="">بدون اپراتور</option>
                      {operatorOptions.map((item) => <option key={item.id} value={item.id}>{item.display_name ?? item.email}</option>)}
                    </select>
                  ) : (row.user_name ?? "—")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
