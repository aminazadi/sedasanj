import { Icon } from "./SiteIcon";

/** Numbered RTL pagination with ellipses; `onChange` receives the 1-based page. */
export default function Pagination({ page, pages, onChange }: { page: number; pages: number; onChange: (page: number) => void }) {
  if (pages <= 1) return null;
  const shown = new Set<number>([1, pages, page - 1, page, page + 1]);
  const list = [...shown].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const fa = (n: number) => n.toLocaleString("fa-IR");
  const items: (number | "gap")[] = [];
  list.forEach((n, i) => { if (i > 0 && n - list[i - 1] > 1) items.push("gap"); items.push(n); });
  return <nav className="help-pagination" aria-label="صفحه‌بندی مقاله‌ها">
    <button type="button" aria-label="صفحهٔ قبل" disabled={page <= 1} onClick={() => onChange(page - 1)}><Icon name="back" size={18} /></button>
    {items.map((n, i) => n === "gap"
      ? <span key={`g${i}`} aria-hidden="true">…</span>
      : <button key={n} type="button" aria-label={`صفحهٔ ${fa(n)}`} aria-current={n === page ? "page" : undefined} className={n === page ? "is-current" : undefined} onClick={() => onChange(n)}>{fa(n)}</button>)}
    <button type="button" aria-label="صفحهٔ بعد" disabled={page >= pages} onClick={() => onChange(page + 1)}><Icon name="arrow" size={18} /></button>
  </nav>;
}
