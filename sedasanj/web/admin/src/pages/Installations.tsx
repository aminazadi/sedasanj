import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Page } from "../types";

interface Installation {
  id: string;
  tenant_id: string;
  tenant_name: string;
  order_id: string | null;
  kind: string;
  status: string;
  pbx_type: string;
  pbx_version: string | null;
  extension_count: number;
  connection_method: string;
  technical_contact: string;
  preferred_time: string | null;
  notes: string | null;
  internal_notes: string | null;
  scheduled_at: string | null;
  created_at: string;
}

interface InstallationEdit {
  item: Installation;
  status: string;
  notes: string;
  scheduledAt: string;
}

function localDateTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function displayDateTime(value: string): string {
  return Number.isNaN(new Date(value).getTime()) ? value : fmt.dateTime(value);
}

export default function Installations() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Page<Installation> | null>(null);
  const [edit, setEdit] = useState<InstallationEdit | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      setPage(await request<Page<Installation>>(`/v1/admin/commerce/installations?limit=${limit}&cursor=${offset}`));
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  useEffect(() => {
    void load();
  }, [offset]);

  function beginUpdate(item: Installation, status: string) {
    setEdit({ item, status, notes: item.internal_notes ?? "", scheduledAt: localDateTime(item.scheduled_at) });
  }

  async function update() {
    if (!edit) return;
    if (edit.status === "scheduled" && !edit.scheduledAt) {
      setError("زمان اجرای نصب را انتخاب کنید.");
      return;
    }
    try {
      await request(`/v1/admin/commerce/installations/${edit.item.id}`, {
        method: "PATCH",
        body: {
          status: edit.status,
          internal_notes: edit.notes || null,
          ...(edit.status === "scheduled" ? { scheduled_at: new Date(edit.scheduledAt).toISOString() } : {}),
        },
      });
      setEdit(null);
      setError(null);
      await load();
    } catch (reason) {
      setError((reason as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <div><h1 className="text-2xl font-bold">نصب و استقرار</h1><p className="mt-1 text-sm text-slate-500">جزئیات فنی، سفارش مرتبط و زمان‌بندی اجرا</p></div>
      <ErrorBox message={error} />
      <div className="card overflow-x-auto">
        {!page ? <Loading /> : page.items.length === 0 ? <Empty /> : (
          <table className="table">
            <thead><tr><th>سازمان</th><th>نوع</th><th>PBX</th><th>داخلی</th><th>مسئول فنی</th><th>زمان‌بندی</th><th>وضعیت</th></tr></thead>
            <tbody>{page.items.map((item) => (
              <tr key={item.id}>
                <td><Link className="text-brand-600" to={`/tenants/${item.tenant_id}`}>{item.tenant_name}</Link>{item.order_id ? <small className="block" dir="ltr">{item.order_id}</small> : null}</td>
                <td>{item.kind}</td>
                <td>{item.pbx_type}<small className="block">{item.pbx_version ?? item.connection_method}</small></td>
                <td>{fmt.int(item.extension_count)}</td>
                <td>{item.technical_contact}</td>
                <td>{item.scheduled_at ? fmt.dateTime(item.scheduled_at) : item.preferred_time ? displayDateTime(item.preferred_time) : "—"}</td>
                <td>
                  <select className="input min-w-36" value={item.status} onChange={(event) => beginUpdate(item, event.target.value)}>
                    <option value="requested">درخواست‌شده</option><option value="paid">پرداخت‌شده</option><option value="reviewing">در بررسی</option><option value="scheduled">زمان‌بندی‌شده</option><option value="in_progress">در حال اجرا</option><option value="completed">تکمیل‌شده</option><option value="canceled">لغوشده</option>
                  </select>
                  {item.internal_notes ? <small className="mt-1 block text-amber-700">{item.internal_notes}</small> : null}
                </td>
              </tr>
            ))}</tbody>
          </table>
        )}
        {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
      </div>

      {edit ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 sm:items-center" role="dialog" aria-modal="true" aria-label="ویرایش وضعیت نصب">
          <div className="card max-h-[calc(100dvh-2rem)] w-full max-w-lg space-y-4 overflow-y-auto sm:max-h-none sm:overflow-visible">
            <div><h2 className="font-bold">ویرایش وضعیت نصب</h2><p className="mt-1 text-sm text-slate-500">{edit.item.tenant_name}</p></div>
            {edit.status === "scheduled" ? <div><label className="label">تاریخ و ساعت اجرا</label><JalaliDatePicker includeTime value={edit.scheduledAt} onChange={(scheduledAt) => setEdit({ ...edit, scheduledAt })} placeholder="انتخاب زمان اجرا" /></div> : null}
            <div><label className="label">یادداشت داخلی</label><textarea className="input min-h-24" value={edit.notes} onChange={(event) => setEdit({ ...edit, notes: event.target.value })} /></div>
            <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={() => setEdit(null)}>انصراف</button><button type="button" className="btn" onClick={() => void update()}>ذخیره</button></div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
