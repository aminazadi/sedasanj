import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { useReasonDialog } from "../components/ReasonDialog";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import { toOffset, useUrlParams } from "../lib/useUrlParams";
import type { Package, Page } from "../types";

const EMPTY = { name: "", minutes: 500, price_toman: 5000000, active: true };

export default function Packages() {
  const limit = 25;
  const [filters, setFilters] = useUrlParams({ offset: "0" });
  const offset = toOffset(filters.offset);
  const setOffset = (value: number) => setFilters({ offset: String(value) });
  const [ask, dialog] = useReasonDialog();
  const [editing, setEditing] = useState<{ id: string; name: string; minutes: number; price_toman: number } | null>(null);
  const [page, setPage] = useState<Page<Package> | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      setPage(await request<Page<Package>>(`/v1/admin/packages?offset=${offset}&limit=${limit}`));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    void reload();
  }, [offset]);
  const packages = page?.items ?? null;

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await request<Package>("/v1/admin/packages", { method: "POST", body: form });
      setForm(EMPTY);
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function save(pkg: Package) {
    if (!editing) return;
    const result = await ask(`ویرایش بستهٔ «${pkg.name}»؛ این تغییر روی خریدهای بعدی اثر می‌گذارد.`);
    if (!result) return;
    setError(null);
    try {
      await request(`/v1/admin/packages/${pkg.id}`, { method: "PATCH", body: { name: editing.name.trim(), minutes: editing.minutes, price_toman: editing.price_toman, reason: result.reason } });
      setEditing(null);
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function toggle(pkg: Package) {
    const result = await ask(pkg.active ? `بستهٔ «${pkg.name}» غیرفعال می‌شود.` : `بستهٔ «${pkg.name}» دوباره فعال می‌شود.`);
    if (!result) return;
    setError(null);
    try {
      if (pkg.active) await request(`/v1/admin/packages/${pkg.id}`, { method: "DELETE" });
      else await request(`/v1/admin/packages/${pkg.id}`, { method: "PATCH", body: { active: true, reason: result.reason } });
      await reload();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      {dialog}
      <ErrorBox message={error} />
      <form className="card grid gap-3 md:grid-cols-4" onSubmit={create}>
        <div className="md:col-span-2">
          <label className="label">نام بسته</label>
          <input
            className="input"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
        </div>
        <div>
          <label className="label">دقیقه</label>
          <input
            className="input"
            type="text"
            inputMode="numeric"
            value={fmt.digits(form.minutes)}
            onChange={(event) =>
              setForm({ ...form, minutes: Number(fmt.latinDigits(event.target.value)) })
            }
          />
        </div>
        <div>
          <label className="label">قیمت (تومان)</label>
          <input
            className="input"
            type="text"
            inputMode="numeric"
            value={fmt.digits(form.price_toman)}
            onChange={(event) =>
              setForm({ ...form, price_toman: Number(fmt.latinDigits(event.target.value)) })
            }
          />
        </div>
        <div className="md:col-span-4">
          <button className="btn">افزودن بسته</button>
        </div>
      </form>

      <div className="card">
        {!packages ? (
          <Loading />
        ) : packages.length === 0 ? (
          <Empty />
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>نام</th>
                <th>دقیقه</th>
                <th>قیمت</th>
                <th>وضعیت</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {packages.map((pkg) => (
                <tr key={pkg.id}>
                  {editing?.id === pkg.id ? (
                    <>
                      <td><input className="input" value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /></td>
                      <td><input className="input" inputMode="numeric" value={fmt.digits(editing.minutes)} onChange={(event) => setEditing({ ...editing, minutes: Number(fmt.latinDigits(event.target.value)) || 0 })} /></td>
                      <td><input className="input" inputMode="numeric" value={fmt.digits(editing.price_toman)} onChange={(event) => setEditing({ ...editing, price_toman: Number(fmt.latinDigits(event.target.value)) || 0 })} /></td>
                      <td>{pkg.active ? "فعال" : "غیرفعال"}</td>
                      <td>
                        <button className="btn-ghost text-xs" disabled={!editing.name.trim() || editing.minutes < 1 || editing.price_toman < 1} onClick={() => void save(pkg)}>ذخیره</button>
                        <button className="btn-ghost text-xs" onClick={() => setEditing(null)}>انصراف</button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{pkg.name}</td>
                      <td>{fmt.int(pkg.minutes)}</td>
                      <td>{fmt.toman(pkg.price_toman)}</td>
                      <td>{pkg.active ? "فعال" : "غیرفعال"}</td>
                      <td>
                        <button className="btn-ghost text-xs" onClick={() => setEditing({ id: pkg.id, name: pkg.name, minutes: pkg.minutes, price_toman: pkg.price_toman })}>ویرایش</button>
                        <button className="btn-ghost text-xs" onClick={() => void toggle(pkg)}>{pkg.active ? "غیرفعال" : "فعال‌سازی"}</button>
                      </td>
                    </>
                  )}
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
