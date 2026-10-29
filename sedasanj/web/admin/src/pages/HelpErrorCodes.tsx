import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { request } from "../api";
import { Empty, ErrorBox, Loading } from "../components/Widgets";
import type { HelpArticle, HelpErrorCode, HelpSeverity } from "../types";

const SEVERITY: Record<HelpSeverity, { label: string; className: string }> = {
  info: { label: "اطلاع", className: "bg-sky-50 text-sky-700" },
  warning: { label: "هشدار", className: "bg-amber-50 text-amber-700" },
  error: { label: "خطا", className: "bg-rose-50 text-rose-700" },
  critical: { label: "بحرانی", className: "bg-rose-100 text-rose-800" },
};

export default function HelpErrorCodes() {
  const navigate = useNavigate();
  const [codes, setCodes] = useState<HelpErrorCode[] | null>(null);
  const [onlyMissing, setOnlyMissing] = useState(false);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setCodes(await request<HelpErrorCode[]>("/v1/admin/help/error-codes"));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (codes ?? []).filter(
      (c) =>
        (!onlyMissing || !c.article_published) &&
        (!needle || c.code.toLowerCase().includes(needle) || c.title.toLowerCase().includes(needle)),
    );
  }, [codes, onlyMissing, filter]);

  async function seed() {
    setBusy(true);
    setMessage(null);
    try {
      const result = await request<{ created: number; updated: number }>("/v1/admin/help/error-codes/seed-module", {
        method: "POST",
      });
      setMessage(`${result.created} کد جدید اضافه و ${result.updated} کد به‌روزرسانی شد.`);
      await reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function createArticle(code: HelpErrorCode) {
    setBusy(true);
    try {
      const article = await request<HelpArticle>("/v1/admin/help/articles", {
        method: "POST",
        body: {
          slug: code.code.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""),
          title: code.title || code.code,
          summary: code.quick_action,
          body_html:
            `<h2>علائم</h2><p>${code.title || code.code}</p><h2>علت</h2><p></p>` +
            `<h2>راه‌حل</h2><p>${code.quick_action}</p><h2>چطور مطمئن شوم درست شد؟</h2><p></p>`,
          kind: "error",
          error_codes: [code.code],
        },
      });
      navigate(`/help/articles/${article.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const missing = (codes ?? []).filter((c) => !c.article_published).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold text-slate-900">کدهای خطا</h1>
          <p className="text-sm text-slate-500">
            هر کد خطای ماژول FreePBX به نشانی /help/errors/کد باز می‌شود. اینجا کدی را به مقاله وصل می‌کنید.
          </p>
        </div>
        <button type="button" className="btn" disabled={busy} onClick={() => void seed()}>
          افزودن کدهای ماژول
        </button>
      </div>
      <ErrorBox message={error} />
      {message ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{message}</div>
      ) : null}
      <div className="card flex flex-wrap items-end gap-3">
        <div>
          <label className="label">جستجو</label>
          <input className="input" dir="ltr" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="SS-UPL-0401" />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyMissing} onChange={(e) => setOnlyMissing(e.target.checked)} />
          فقط کدهای بدون مقالهٔ منتشرشده
        </label>
        <div className="text-sm text-slate-500">{missing} کد هنوز مقالهٔ منتشرشده ندارد.</div>
      </div>
      {codes === null ? (
        <Loading />
      ) : visible.length === 0 ? (
        <Empty>کدی یافت نشد. برای شروع «افزودن کدهای ماژول» را بزنید.</Empty>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="table">
            <thead>
              <tr>
                <th>کد</th>
                <th>شدت</th>
                <th>توضیح</th>
                <th>مقاله</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((c) => (
                <tr key={c.code}>
                  <td dir="ltr" className="font-mono text-xs">
                    {c.code}
                  </td>
                  <td>
                    <span className={`badge ${SEVERITY[c.severity].className}`}>{SEVERITY[c.severity].label}</span>
                  </td>
                  <td className="max-w-md text-sm">{c.title}</td>
                  <td>
                    {c.article_slug ? (
                      <span>
                        {c.article_title}{" "}
                        <span className={`badge ${c.article_published ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
                          {c.article_published ? "منتشرشده" : "پیش‌نویس"}
                        </span>
                      </span>
                    ) : (
                      <button type="button" className="btn btn-ghost btn-sm" disabled={busy} onClick={() => void createArticle(c)}>
                        ساخت مقاله
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-slate-400">
        برای ویرایش یک مقاله به <Link className="underline" to="/help/articles">فهرست مقاله‌ها</Link> بروید.
      </p>
    </div>
  );
}
