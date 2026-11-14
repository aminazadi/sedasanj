import RelatedArticles from "../components/RelatedArticles";
import ArticleCard from "../components/ArticleCard";
import Pagination from "../components/Pagination";
import { Icon } from "../components/SiteIcon";
import DOMPurify from "dompurify";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import PublicPageFrame from "../components/PublicPageFrame";
import { HeroArt } from "../components/SitePageParts";
import { EMPTY_STATE_ART } from "../components/pageArt";
import { request } from "../api";
import { useArticleSeo } from "../seo/useArticleSeo";

interface Category { id: string; slug: string; title: string; description: string; article_count: number }
interface Summary { thumbnail_url?: string | null; category_title?: string | null; id: string; slug: string; title: string; summary: string; kind: string; category_id: string | null; published_at: string | null }
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
  const body = <main className={framed ? "page-main" : "page-main panel-help"}><div className="site-container help-page" dir="rtl">{children}</div></main>;
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

const PAGE_SIZE = 12;
const MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
interface ArchiveMonth { month: string; count: number }
const monthLabel = (key: string) => `${MONTHS[Number(key.slice(5)) - 1] ?? ""} ${Number(key.slice(0, 4)).toLocaleString("fa-IR", { useGrouping: false })}`;

export function HelpHome({ framed }: { framed: boolean }) {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const month = params.get("month") ?? "";
  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);
  const [q, setQ] = useState(query);
  useEffect(() => setQ(query), [query]);
  const categories = useLoad<Category[]>("/v1/help/categories");
  const archive = useLoad<ArchiveMonth[]>("/v1/help/archive");
  const path = useMemo(() => {
    const p = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String((page - 1) * PAGE_SIZE) });
    if (query) p.set("q", query);
    if (category) p.set("category", category);
    if (month) p.set("month", month);
    return `/v1/help/articles?${p}`;
  }, [query, category, month, page]);
  const list = useLoad<{ items: Summary[]; total: number }>(path);
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / PAGE_SIZE));
  const visibleCategories = (categories.data ?? []).filter((c) => c.article_count > 0);
  const activeCategory = visibleCategories.find((c) => c.slug === category);
  const filtered = Boolean(query || category || month);

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) { if (v) merged.set(k, v); else merged.delete(k); }
    if (!("page" in next)) merged.delete("page");
    setParams(merged);
  }
  const heading = query ? `نتایج جستجو برای «${query}»` : activeCategory ? activeCategory.title : month ? `آرشیو ${monthLabel(month)}` : "تازه‌ترین مقاله‌ها";

  return (
    <Shell framed={framed}>
      <header className="help-hero">
        {framed ? <HeroArt page="help"/> : null}
        <h1>{framed ? "مرکز راهنمای صداسنج" : "مقالات و آموزش‌ها"}</h1>
        <p>آموزش استفاده از صداسنج، راه‌اندازی سرویس‌ها، رفع خطاها و پرسش‌های متداول.</p>
        <form onSubmit={(e) => { e.preventDefault(); update({ q: q.trim() }); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="جستجو در راهنما" aria-label="جستجو" />
          <button type="submit" aria-label="جستجو"><Icon name="search" size={20}/></button>
        </form>
      </header>
      {visibleCategories.length > 0 ? (
        <nav className="help-categories" aria-label="دسته‌بندی مقاله‌ها">
          <button type="button" className={`help-category${!category ? " is-active" : ""}`} aria-pressed={!category} onClick={() => update({ category: "" })}>همهٔ مقاله‌ها</button>
          {visibleCategories.map((c) => (
            <button type="button" key={c.id} title={c.description || undefined} className={`help-category${category === c.slug ? " is-active" : ""}`} aria-pressed={category === c.slug} onClick={() => update({ category: category === c.slug ? "" : c.slug })}>
              {c.title}<em>{c.article_count.toLocaleString("fa-IR")}</em>
            </button>
          ))}
        </nav>
      ) : null}
      <div className="help-layout">
        <section className="help-list" aria-live="polite">
          <div className="help-list-head">
            <h2>{heading}</h2>
            <div className="help-list-tools">
              {list.data ? <span>{list.data.total.toLocaleString("fa-IR")} مقاله</span> : null}
              {archive.data && archive.data.length > 0 ? (
                <select className="help-archive-select" aria-label="آرشیو بر اساس ماه" value={month} onChange={(e) => update({ month: e.target.value })}>
                  <option value="">آرشیو: همهٔ ماه‌ها</option>
                  {archive.data.map((m) => <option key={m.month} value={m.month}>{monthLabel(m.month)} ({m.count.toLocaleString("fa-IR")})</option>)}
                </select>
              ) : null}
            </div>
          </div>
          {list.error ? <p className="help-error">بارگذاری ناموفق بود. کمی بعد دوباره تلاش کنید.</p> : null}
          {list.data && list.data.items.length === 0 ? <div className="help-empty" role="status">
            <img src={EMPTY_STATE_ART} alt="" width={240} height={150} />
            <b>{filtered ? "مقاله‌ای با این فیلتر پیدا نشد" : "هنوز مقاله‌ای منتشر نشده است"}</b>
            <span>{filtered ? "فیلتر را بردارید یا عبارت دیگری را امتحان کنید." : "کمی بعد دوباره سر بزنید."}</span>
            {filtered ? <button type="button" onClick={() => setParams({})}><Icon name="refresh" size={18}/>نمایش همهٔ مقاله‌ها</button> : null}
          </div> : null}
          <div className="help-grid">
            {(list.data?.items ?? []).map((a) => <ArticleCard key={a.id} article={a} />)}
          </div>
          <Pagination page={Math.min(page, pages)} pages={pages} onChange={(n) => { update({ page: n > 1 ? String(n) : "" }); window.scrollTo({ top: 0 }); }} />
        </section>
      </div>
    </Shell>
  );
}

export function HelpArticlePage({ framed }: { framed: boolean }) {
  const { slug = "" } = useParams();
  const { data, error } = useLoad<Article>(`/v1/help/articles/${encodeURIComponent(slug)}`);
  const html = useMemo(() => (data ? cleanHtml(data.body_html) : ""), [data]);
  const more = useLoad<{ items: Summary[] }>(data ? "/v1/help/articles?kind=article&limit=10" : "/v1/help/articles?limit=1&q=__none__");
  const related = (more.data?.items ?? []).filter((a) => a.slug !== slug).slice(0, 9);
  useArticleSeo(data, error === "notfound");
  return (
    <Shell framed={framed}>
      <p><Link className="help-back-link" to="/help"><Icon name="back" size={18}/>مرکز راهنما</Link></p>
      {error === "notfound" ? <NotFound /> : error ? <p className="help-error">بارگذاری ناموفق بود.</p> : null}
      {data ? (
        <article className="help-article">
          <h1>{data.title}</h1>
          {data.thumbnail_url ? <img className="article-cover" src={data.thumbnail_url} alt={data.title} width={1200} height={675} /> : null}
          {data.published_at ? <p className="help-date"><time dateTime={data.published_at}>{new Intl.DateTimeFormat("fa-IR", { year: "numeric", month: "long", day: "numeric" }).format(new Date(data.published_at))}</time></p> : null}
          {data.error_codes.length > 0 ? <p className="help-codes">{data.error_codes.map((c) => <Code key={c}>{c}</Code>)}</p> : null}
          <div className="prose-help" dangerouslySetInnerHTML={{ __html: html }} />
        </article>
      ) : null}
      {data && related.length > 0 ? <RelatedArticles key={slug} items={related} /> : null}
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
      <p><Link className="help-back-link" to="/help"><Icon name="back" size={18}/>مرکز راهنما</Link></p>
      {info.error === "notfound" ? <NotFound /> : null}
      {info.data ? (
        <article className="help-article">
          <h1><Code>{info.data.code}</Code> {info.data.title}</h1>
          {article.data?.thumbnail_url ? <img className="article-cover" src={article.data.thumbnail_url} alt={article.data.title} width={1200} height={675} /> : null}
          {info.data.quick_action ? <p className="help-quick"><b>اقدام سریع:</b> {info.data.quick_action}</p> : null}
          {info.data.article_slug && article.data ? <div className="prose-help" dangerouslySetInnerHTML={{ __html: html }} /> : (
            <p className="help-empty">راهنمای کامل این خطا هنوز منتشر نشده است. اگر مشکل ادامه داشت، فایل پشتیبانی (Support bundle) را از صفحهٔ ماژول دانلود کنید و با پشتیبانی تماس بگیرید.</p>
          )}
        </article>
      ) : null}
    </Shell>
  );
}
