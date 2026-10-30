import DOMPurify from "dompurify";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import PublicPageFrame from "../components/PublicPageFrame";
import { HeroArt } from "../components/SitePageParts";
import { request } from "../api";

interface Category { id: string; slug: string; title: string; description: string; article_count: number }
interface Summary { id: string; slug: string; title: string; summary: string; kind: string; category_id: string | null; published_at: string | null }
interface Article extends Summary { body_html: string; error_codes: string[]; updated_at: string }
interface ErrorCode { code: string; severity: string; title: string; quick_action: string; article_slug: string | null; article_title: string | null; article_published: boolean }

/** Second layer after the server allowlist: keep platform media and the two embed hosts, drop the rest. */
function cleanHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ["iframe", "video", "figure", "figcaption"],
    ADD_ATTR: ["target", "controls", "allowfullscreen", "allow", "loading", "referrerpolicy", "sandbox", "poster", "preload"],
    FORBID_TAGS: ["style", "script"],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|\/|#)/i,
  });
}

function Code({ children }: { children: string }) {
  return <bdi dir="ltr" data-keep-latin-digits className="help-code">{children}</bdi>;
}

function Shell({ framed, children }: { framed: boolean; children: ReactNode }) {
  const body = <main className="page-main"><div className="site-container help-page" dir="rtl">{children}</div></main>;
  return framed ? <PublicPageFrame>{body}</PublicPageFrame> : body;
}

function useLoad<T>(path: string): { data: T | null; error: string | null } {
  const [state, setState] = useState<{ data: T | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let live = true;
    setState({ data: null, error: null });
    request<T>(path).then(
      (data) => live && setState({ data, error: null }),
      (err: Error & { status?: number }) => live && setState({ data: null, error: err.status === 404 ? "notfound" : err.message }),
    );
    return () => { live = false; };
  }, [path]);
  return state;
}

function NotFound() {
  return <div className="help-empty"><h1>این صفحه پیدا نشد</h1><p>ممکن است هنوز منتشر نشده باشد. از <Link to="/help">مرکز راهنما</Link> جستجو کنید یا با پشتیبانی تماس بگیرید.</p></div>;
}

export function HelpHome({ framed }: { framed: boolean }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const categories = useLoad<Category[]>("/v1/help/categories");
  const path = useMemo(() => `/v1/help/articles?limit=50${query ? `&q=${encodeURIComponent(query)}` : ""}`, [query]);
  const list = useLoad<{ items: Summary[]; total: number }>(path);
  return (
    <Shell framed={framed}>
      <header className="help-hero">
        {framed ? <HeroArt/> : null}
        <h1>مرکز راهنمای صداسنج</h1>
        <p>نصب ماژول FreePBX، رفع خطاها و پرسش‌های متداول.</p>
        <form onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو؛ مثلاً SS-UPL-0401 یا کلید API" aria-label="جستجو" />
          <button type="submit">جستجو</button>
        </form>
      </header>
      {!query && categories.data && categories.data.length > 0 ? (
        <section className="help-categories">
          {categories.data.filter((c) => c.article_count > 0).map((c) => (
            <div key={c.id} className="help-category">
              <b>{c.title}</b><span>{c.description}</span>
            </div>
          ))}
        </section>
      ) : null}
      <section className="help-list">
        <h2>{query ? `نتایج جستجو برای «${query}»` : "همهٔ مقاله‌ها"}</h2>
        {list.error ? <p className="help-error">بارگذاری ناموفق بود. کمی بعد دوباره تلاش کنید.</p> : null}
        {list.data && list.data.items.length === 0 ? <p>موردی پیدا نشد.</p> : null}
        <ul>
          {(list.data?.items ?? []).map((a) => (
            <li key={a.id}><Link to={`/help/${a.slug}`}>{a.title}</Link>{a.summary ? <p>{a.summary}</p> : null}</li>
          ))}
        </ul>
      </section>
    </Shell>
  );
}

export function HelpArticlePage({ framed }: { framed: boolean }) {
  const { slug = "" } = useParams();
  const { data, error } = useLoad<Article>(`/v1/help/articles/${encodeURIComponent(slug)}`);
  const html = useMemo(() => (data ? cleanHtml(data.body_html) : ""), [data]);
  const more = useLoad<{ items: Summary[] }>(data ? "/v1/help/articles?kind=article&limit=4" : "/v1/help/articles?limit=1&q=__none__");
  const related = (more.data?.items ?? []).filter((a) => a.slug !== slug).slice(0, 3);
  useEffect(() => {
    if (data) document.title = `${data.title} | صداسنج`;
  }, [data]);
  return (
    <Shell framed={framed}>
      <p><Link to="/help">← مرکز راهنما</Link></p>
      {error === "notfound" ? <NotFound /> : error ? <p className="help-error">بارگذاری ناموفق بود.</p> : null}
      {data ? (
        <article className="help-article">
          <h1>{data.title}</h1>
          {data.published_at ? <p className="help-date"><time dateTime={data.published_at}>{new Intl.DateTimeFormat("fa-IR", { year: "numeric", month: "long", day: "numeric" }).format(new Date(data.published_at))}</time></p> : null}
          {data.error_codes.length > 0 ? <p className="help-codes">{data.error_codes.map((c) => <Code key={c}>{c}</Code>)}</p> : null}
          <div className="prose-help" dangerouslySetInnerHTML={{ __html: html }} />
        </article>
      ) : null}
      {data && related.length > 0 ? (
        <section className="help-list">
          <h2>مقالات بیشتر</h2>
          <ul>{related.map((a) => <li key={a.id}><Link to={`/help/${a.slug}`}>{a.title}</Link>{a.summary ? <p>{a.summary}</p> : null}</li>)}</ul>
        </section>
      ) : null}
    </Shell>
  );
}

/** Deep link used by the FreePBX module: /help/errors/SS-UPL-0401 */
export function HelpErrorPage({ framed }: { framed: boolean }) {
  const { code = "" } = useParams();
  const info = useLoad<ErrorCode>(`/v1/help/errors/${encodeURIComponent(code)}`);
  const article = useLoad<Article>(info.data?.article_slug ? `/v1/help/articles/${encodeURIComponent(info.data.article_slug)}` : "/v1/help/articles/__none__");
  const html = useMemo(() => (article.data && info.data?.article_slug ? cleanHtml(article.data.body_html) : ""), [article.data, info.data]);
  return (
    <Shell framed={framed}>
      <p><Link to="/help">← مرکز راهنما</Link></p>
      {info.error === "notfound" ? <NotFound /> : null}
      {info.data ? (
        <article className="help-article">
          <h1><Code>{info.data.code}</Code> {info.data.title}</h1>
          {info.data.quick_action ? <p className="help-quick"><b>اقدام سریع:</b> {info.data.quick_action}</p> : null}
          {info.data.article_slug && article.data ? <div className="prose-help" dangerouslySetInnerHTML={{ __html: html }} /> : (
            <p className="help-empty">راهنمای کامل این خطا هنوز منتشر نشده است. اگر مشکل ادامه داشت، فایل پشتیبانی (Support bundle) را از صفحهٔ ماژول دانلود کنید و با پشتیبانی تماس بگیرید.</p>
          )}
        </article>
      ) : null}
    </Shell>
  );
}
