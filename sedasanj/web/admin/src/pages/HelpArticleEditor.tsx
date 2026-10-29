import { lazy, Suspense, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { request } from "../api";
import HelpMediaLibrary, { mediaHtml } from "../components/HelpMediaLibrary";
import { ErrorBox, Loading } from "../components/Widgets";
import { sanitizeHelpHtml } from "../sanitize";
import type { HelpArticle, HelpCategory, HelpKind } from "../types";

const RichTextEditor = lazy(() => import("../components/RichTextEditor"));

interface Form {
  title: string;
  slug: string;
  summary: string;
  kind: HelpKind;
  category_id: string;
  position: string;
  error_codes: string;
  body_html: string;
}

const EMPTY: Form = {
  title: "",
  slug: "",
  summary: "",
  kind: "article",
  category_id: "",
  position: "0",
  error_codes: "",
  body_html: "",
};

const ERROR_TEMPLATE =
  "<h2>علائم</h2><p></p><h2>علت</h2><p></p><h2>راه‌حل</h2><ol><li></li></ol>" +
  "<h2>چطور مطمئن شوم درست شد؟</h2><p></p><h2>پیشگیری</h2><p></p>";

function toForm(article: HelpArticle): Form {
  return {
    title: article.title,
    slug: article.slug,
    summary: article.summary,
    kind: article.kind,
    category_id: article.category_id ?? "",
    position: String(article.position),
    error_codes: article.error_codes.join(", "),
    body_html: article.body_html,
  };
}

function parseCodes(text: string): string[] {
  return Array.from(new Set(text.split(/[\s,،]+/).map((c) => c.trim()).filter(Boolean)));
}

export default function HelpArticleEditor() {
  const { articleId } = useParams();
  const navigate = useNavigate();
  const isNew = articleId === "new";
  const [form, setForm] = useState<Form>(EMPTY);
  const [article, setArticle] = useState<HelpArticle | null>(null);
  const [categories, setCategories] = useState<HelpCategory[]>([]);
  const [loading, setLoading] = useState(!isNew);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);
  const [insertMedia, setInsertMedia] = useState<((html: string) => void) | null>(null);

  useEffect(() => {
    void request<HelpCategory[]>("/v1/admin/help/categories").then(setCategories, () => undefined);
  }, []);

  useEffect(() => {
    if (isNew) return;
    setLoading(true);
    request<HelpArticle>(`/v1/admin/help/articles/${articleId}`)
      .then((a) => {
        setArticle(a);
        setForm(toForm(a));
      })
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, [articleId, isNew]);

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));

  function payload() {
    return {
      slug: form.slug.trim().toLowerCase(),
      title: form.title.trim(),
      summary: form.summary.trim(),
      body_html: form.body_html,
      kind: form.kind,
      category_id: form.category_id || null,
      clear_category: !form.category_id,
      position: Number(form.position) || 0,
      error_codes: parseCodes(form.error_codes),
    };
  }

  async function save(): Promise<HelpArticle | null> {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const body = payload();
      const result = isNew
        ? await request<HelpArticle>("/v1/admin/help/articles", { method: "POST", body })
        : await request<HelpArticle>(`/v1/admin/help/articles/${articleId}`, { method: "PATCH", body });
      setArticle(result);
      setForm(toForm(result));
      setSaved("ذخیره شد.");
      if (isNew) navigate(`/help/articles/${result.id}`, { replace: true });
      return result;
    } catch (err) {
      setError((err as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function togglePublish() {
    const current = await save();
    if (!current) return;
    setBusy(true);
    try {
      const action = current.status === "published" ? "unpublish" : "publish";
      const result = await request<HelpArticle>(`/v1/admin/help/articles/${current.id}/${action}`, { method: "POST" });
      setArticle(result);
      setSaved(result.status === "published" ? "منتشر شد." : "به پیش‌نویس برگشت.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!article || !window.confirm("این مقاله حذف شود؟ کدهای خطای متصل به آن بدون مقاله می‌مانند.")) return;
    try {
      await request(`/v1/admin/help/articles/${article.id}`, { method: "DELETE" });
      navigate("/help/articles");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (loading) return <Loading />;

  const published = article?.status === "published";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/help/articles" className="text-sm text-slate-500">
            ← مقاله‌های راهنما
          </Link>
          <h1 className="text-xl font-extrabold text-slate-900">{isNew ? "مقالهٔ جدید" : form.title || "ویرایش مقاله"}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {article ? (
            <span className={`badge ${published ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-600"}`}>
              {published ? "منتشرشده" : "پیش‌نویس"}
            </span>
          ) : null}
          {published && article ? (
            <a className="btn btn-ghost" href={`/help/${article.slug}`} target="_blank" rel="noreferrer">
              دیدن در سایت
            </a>
          ) : null}
          <button type="button" className="btn btn-ghost" onClick={() => setPreview((p) => !p)}>
            {preview ? "ویرایش" : "پیش‌نمایش"}
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => void save()}>
            ذخیره
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => void togglePublish()}>
            {published ? "بازگشت به پیش‌نویس" : "ذخیره و انتشار"}
          </button>
          {article ? (
            <button type="button" className="btn btn-ghost text-rose-600" onClick={() => void remove()}>
              حذف
            </button>
          ) : null}
        </div>
      </div>
      <ErrorBox message={error} />
      {saved ? (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{saved}</div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="space-y-4">
          <div className="card space-y-3">
            <div>
              <label className="label">عنوان</label>
              <input className="input" value={form.title} maxLength={250} onChange={(e) => set("title", e.target.value)} />
            </div>
            <div>
              <label className="label">خلاصه (در فهرست و نتایج جستجو)</label>
              <textarea className="input" rows={2} maxLength={1000} value={form.summary} onChange={(e) => set("summary", e.target.value)} />
            </div>
          </div>
          <div className="card">
            {preview ? (
              <div
                className="prose-help min-h-[20rem]"
                dir="rtl"
                dangerouslySetInnerHTML={{ __html: sanitizeHelpHtml(form.body_html) }}
              />
            ) : (
              <Suspense fallback={<Loading />}>
                <RichTextEditor
                  value={form.body_html}
                  onChange={(html) => set("body_html", html)}
                  minHeight={460}
                  onPickMedia={(insert) => setInsertMedia(() => insert)}
                />
              </Suspense>
            )}
            {form.kind === "error" && !form.body_html.trim() ? (
              <button type="button" className="btn btn-ghost mt-3" onClick={() => set("body_html", ERROR_TEMPLATE)}>
                درج قالب مقالهٔ خطا (علائم، علت، راه‌حل، تأیید، پیشگیری)
              </button>
            ) : null}
          </div>
        </div>

        <div className="space-y-4">
          <div className="card space-y-3">
            <div>
              <label className="label">نشانی (slug)</label>
              <input
                className="input"
                dir="ltr"
                value={form.slug}
                placeholder="ss-upl-0401"
                onChange={(e) => set("slug", e.target.value.toLowerCase())}
              />
              <p className="mt-1 text-xs text-slate-500" dir="ltr">
                /help/{form.slug || "…"}
              </p>
            </div>
            <div>
              <label className="label">نوع</label>
              <select className="input" value={form.kind} onChange={(e) => set("kind", e.target.value as HelpKind)}>
                <option value="article">مقاله</option>
                <option value="error">توضیح خطا</option>
                <option value="faq">پرسش متداول</option>
              </select>
            </div>
            <div>
              <label className="label">دسته</label>
              <select className="input" value={form.category_id} onChange={(e) => set("category_id", e.target.value)}>
                <option value="">بدون دسته</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">ترتیب</label>
              <input className="input" dir="ltr" inputMode="numeric" value={form.position} onChange={(e) => set("position", e.target.value)} />
            </div>
          </div>
          <div className="card space-y-2">
            <label className="label">کدهای خطای مرتبط</label>
            <textarea
              className="input font-mono text-xs"
              dir="ltr"
              rows={3}
              value={form.error_codes}
              placeholder="SS-UPL-0401, unauthorized"
              onChange={(e) => set("error_codes", e.target.value)}
            />
            <p className="text-xs text-slate-500">
              با ویرگول یا فاصله جدا کنید. نشانی /help/errors/کد به این مقاله می‌رسد (ماژول FreePBX از همین لینک استفاده می‌کند).
            </p>
          </div>
        </div>
      </div>

      {insertMedia ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4" role="dialog" aria-modal="true">
          <div className="w-full max-w-4xl rounded-xl bg-white p-4 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-lg font-bold">کتابخانهٔ تصویر و ویدئو</h2>
              <button type="button" className="btn btn-ghost" onClick={() => setInsertMedia(null)}>
                بستن
              </button>
            </div>
            <HelpMediaLibrary
              onPick={(media) => {
                insertMedia(mediaHtml(media));
                setInsertMedia(null);
              }}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
