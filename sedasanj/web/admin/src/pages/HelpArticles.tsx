import { useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import { FilterSelect, useFilterBar } from "@cbi/web-shared/components/FilterBar";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";
import type { HelpArticleSummary, HelpKind, HelpStatus } from "../types";

interface ArticlePage {
  items: HelpArticleSummary[];
  total: number;
}

const COLUMNS: SkeletonColumn[] = [
  { label: "عنوان", width: "12rem" },
  { label: "نوع", width: "3rem" },
  { label: "وضعیت", kind: "badge" },
  { label: "نشانی", width: "8rem", dir: "ltr" },
  { label: "آخرین ویرایش", width: "5rem" },
];

const KIND_LABEL: Record<HelpKind, string> = { article: "مقاله", error: "خطا", faq: "پرسش متداول" };
const STATUS_META: Record<HelpStatus, { label: string; className: string }> = {
  draft: { label: "پیش‌نویس", className: "bg-slate-100 text-slate-600" },
  published: { label: "منتشرشده", className: "bg-emerald-50 text-emerald-700" },
};

export default function HelpArticles() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<HelpStatus | "">("");
  const [kind, setKind] = useState<HelpKind | "">("");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const articles = useResource<ArticlePage>((signal) => {
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
    if (status) params.set("status", status);
    if (kind) params.set("kind", kind);
    if (query) params.set("q", query);
    return request<ArticlePage>(`/v1/admin/help/articles?${params}`, { signal });
  }, [offset, status, kind, query]);
  const page = articles.data;

  const filterBar = useFilterBar({ hasActive: Boolean(q || query || status || kind), onClear: () => { setQ(""); setQuery(""); setStatus(""); setKind(""); setOffset(0); }, fields: [ { id: "q", label: "جستجو", active: Boolean(q || query), onRemove: () => { setQ(""); setQuery(""); setOffset(0); }, className: "sm:w-64", control: <form onSubmit={(e) => { e.preventDefault(); setOffset(0); setQuery(q.trim()); }}><input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="عنوان یا نشانی" /></form> }, { id: "status", label: "وضعیت", active: Boolean(status), onRemove: () => { setOffset(0); setStatus(""); }, control: <FilterSelect value={status} onChange={(value) => { setOffset(0); setStatus(value as HelpStatus | ""); }} options={[{ value: "published", label: "منتشرشده" }, { value: "draft", label: "پیش‌نویس" }]} /> }, { id: "kind", label: "نوع", active: Boolean(kind), onRemove: () => { setOffset(0); setKind(""); }, control: <FilterSelect value={kind} onChange={(value) => { setOffset(0); setKind(value as HelpKind | ""); }} options={[{ value: "article", label: "مقاله" }, { value: "error", label: "خطا" }, { value: "faq", label: "پرسش متداول" }]} /> }, ] });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold text-slate-900">مقاله‌های راهنما</h1>
          <p className="text-sm text-slate-500">
            متن، تصویر و ویدئو برای صفحهٔ عمومی «مرکز راهنما» و لینک کدهای خطا.
          </p>
        </div>
        <div className="flex flex-wrap items-end justify-end gap-3">
          <Link to="/help/articles/new" className="btn inline-flex min-h-[42px] items-center">
            مقالهٔ جدید
          </Link>
          {filterBar.toolbar}
        </div>
      </div>
      <ErrorBox message={articles.error} />
      {filterBar.fields}
      {articles.loading ? (
        <div className="card overflow-x-auto p-0"><SkeletonTable columns={COLUMNS} rows={page?.items.length ? Math.min(page.items.length, limit) : 8} /></div>
      ) : !page || page.items.length === 0 ? (
        <Empty>هنوز مقاله‌ای نیست. با «مقالهٔ جدید» شروع کنید یا از «کدهای خطا» برای هر کد مقاله بسازید.</Empty>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="table">
            <thead>
              <tr>
                <th>عنوان</th>
                <th>نوع</th>
                <th>وضعیت</th>
                <th>نشانی</th>
                <th>آخرین ویرایش</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Link className="font-bold text-brand-700" to={`/help/articles/${a.id}`}>
                      {a.title}
                    </Link>
                  </td>
                  <td>{KIND_LABEL[a.kind]}</td>
                  <td>
                    <span className={`badge ${STATUS_META[a.status].className}`}>{STATUS_META[a.status].label}</span>
                  </td>
                  <td dir="ltr" className="text-xs text-slate-500">
                    /help/{a.slug}
                  </td>
                  <td>{fmt.date(a.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {page ? <Pagination offset={offset} limit={limit} total={page.total} onChange={setOffset} /> : null}
    </div>
  );
}
