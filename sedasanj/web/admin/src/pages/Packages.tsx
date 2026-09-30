import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { Package, Page } from "../types";

const EMPTY = { name: "", minutes: 500, price_toman: 5000000, active: true };

export default function Packages() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
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

  return (
    <div className="space-y-4">
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
                  <td>{pkg.name}</td>
                  <td>{fmt.int(pkg.minutes)}</td>
                  <td>{fmt.toman(pkg.price_toman)}</td>
                  <td>{pkg.active ? "فعال" : "غیرفعال"}</td>
                  <td>
                    <button
                      className="btn-ghost text-xs"
                      onClick={async () => {
                        const name = window.prompt("نام بسته", pkg.name);
                        const minutes = window.prompt("دقیقه", String(pkg.minutes));
                        const price = window.prompt("قیمت تومان", String(pkg.price_toman));
                        if (!name || !minutes || !price) return;
                        await request(`/v1/admin/packages/${pkg.id}`, { method: "PATCH", body: { name, minutes: Number(fmt.latinDigits(minutes)), price_toman: Number(fmt.latinDigits(price)) } });
                        await reload();
                      }}
                    >
                      ویرایش
                    </button>
                    <button
                      className="btn-ghost text-xs"
                      onClick={async () => {
                        if (pkg.active) await request(`/v1/admin/packages/${pkg.id}`, { method: "DELETE" });
                        else await request(`/v1/admin/packages/${pkg.id}`, { method: "PATCH", body: { active: true } });
                        await reload();
                      }}
                    >
                      {pkg.active ? "غیرفعال" : "فعال‌سازی"}
                    </button>
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
