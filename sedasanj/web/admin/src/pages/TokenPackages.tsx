import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading } from "../components/Widgets";

interface TokenPackage { id: string; name: string; tokens: number; price_toman: number; active: boolean }
const EMPTY = { name: "", tokens: 5_000_000, price_toman: 500_000, active: true };

export default function TokenPackages() {
  const [items, setItems] = useState<TokenPackage[] | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload() {
    try { setItems(await request<TokenPackage[]>("/v1/admin/token-packages")); }
    catch (reason) { setError((reason as Error).message); }
  }
  useEffect(() => { void reload(); }, []);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(null);
    try {
      await request("/v1/admin/token-packages", { method: "POST", retry: false, body: { ...form, name: form.name.trim() } });
      setForm(EMPTY); await reload();
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  async function toggle(pack: TokenPackage) {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      await request(`/v1/admin/token-packages/${pack.id}`, { method: "PATCH", body: { name: pack.name, tokens: pack.tokens, price_toman: pack.price_toman, active: !pack.active } });
      await reload();
    } catch (reason) { setError((reason as Error).message); } finally { setBusy(false); }
  }

  return <div className="space-y-4">
    <ErrorBox message={error}/>
    <form className="card grid gap-3 md:grid-cols-4" onSubmit={create}>
      <label className="md:col-span-2"><span className="label">نام بسته</span><input className="input" required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}/></label>
      <label><span className="label">تعداد توکن</span><input className="input" type="number" required min={1000} value={form.tokens} onChange={(e) => setForm({ ...form, tokens: Number(fmt.latinDigits(e.target.value)) })}/></label>
      <label><span className="label">قیمت (تومان، بدون مالیات)</span><input className="input" type="number" required min={1000} value={form.price_toman} onChange={(e) => setForm({ ...form, price_toman: Number(fmt.latinDigits(e.target.value)) })}/></label>
      <div className="md:col-span-4"><button className="btn" disabled={busy}>افزودن بسته توکن</button></div>
    </form>
    <div className="card overflow-x-auto">
      {!items ? <Loading/> : items.length === 0 ? <Empty/> :
        <table className="table"><thead><tr><th>نام</th><th>توکن</th><th>قیمت</th><th>وضعیت</th><th/></tr></thead>
          <tbody>{items.map((pack) => <tr key={pack.id}>
            <td>{pack.name}</td><td>{fmt.int(pack.tokens)}</td><td>{fmt.toman(pack.price_toman)}</td>
            <td>{pack.active ? "فعال" : "غیرفعال"}</td>
            <td><button className="btn-ghost text-xs" disabled={busy} onClick={() => void toggle(pack)}>{pack.active ? "غیرفعال‌سازی" : "فعال‌سازی"}</button></td>
          </tr>)}</tbody></table>}
    </div>
  </div>;
}
