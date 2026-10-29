import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { HelpArticleSummary, HelpKind, HelpStatus } from "../types";

interface ArticlePage {
  items: HelpArticleSummary[];
  total: number;
}

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
  const [page, setPage] = useState<ArticlePage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (status) params.set("status", status);
      if (kind) params.set("kind", kind);
      if (query) params.set("q", query);
      setPage(await request<ArticlePage>(`/v1/admin/help/articles?${params}`));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [offset, status, kind, query]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold text-slate-900">مقاله‌های راهنما</h1>
          <p className="text-sm text-slate-500">
            متن، تصویر و ویدئو برای صفحهٔ عمومی «مرکز راهنما» و لینک کدهای خطا.
          </p>
        </div>
        <Link to="/help/articles/new" className="btn">
          مقالهٔ جدید
        </Link>
      </div>
      <ErrorBox message={error} />
      <div className="card flex flex-wrap items-end gap-3">
        <div>
          <label className="label">جستجو</label>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setQuery(q.trim());
            }}
          >
            <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="عنوان یا نشانی" />
          </form>
        </div>
        <div>
          <label className="label">وضعیت</label>
          <select
            className="input"
            value={status}
            onChange={(e) => {
              setOffset(0);
              setStatus(e.target.value as HelpStatus | "");
            }}
          >
            <option value="">همه</option>
            <option value="published">منتشرشده</option>
            <option value="draft">پیش‌نویس</option>
          </select>
        </div>
        <div>
          <label className="label">نوع</label>
          <select
            className="input"
            value={kind}
            onChange={(e) => {
              setOffset(0);
              setKind(e.target.value as HelpKind | "");
            }}
          >
            <option value="">همه</option>
            <option value="article">مقاله</option>
            <option value="error">خطا</option>
            <option value="faq">پرسش متداول</option>
          </select>
        </div>
      </div>
      {!page ? (
        <Loading />
      ) : page.items.length === 0 ? (
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
