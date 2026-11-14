import { Link } from "react-router-dom";
import ArticleThumbnail from "./ArticleThumbnail";
import { Icon } from "./SiteIcon";

export interface ArticleCardData {
  id: string; slug: string; title: string; summary: string;
  thumbnail_url?: string | null; category_title?: string | null; published_at: string | null;
}

const dateFmt = new Intl.DateTimeFormat("fa-IR", { year: "numeric", month: "long", day: "numeric" });

/** One uniform card for the help-center grid: cover, category, title, two-line summary, date and link. */
export default function ArticleCard({ article }: { article: ArticleCardData }) {
  const href = `/help/${article.slug}`;
  return <article className="help-card">
    <Link to={href} tabIndex={-1} aria-hidden="true"><ArticleThumbnail src={article.thumbnail_url} /></Link>
    <div className="help-card-body">
      {article.category_title ? <span className="help-card-category">{article.category_title}</span> : null}
      <h3><Link to={href}>{article.title}</Link></h3>
      {article.summary ? <p>{article.summary}</p> : null}
      <div className="help-card-foot">
        {article.published_at ? <time dateTime={article.published_at}>{dateFmt.format(new Date(article.published_at))}</time> : <span />}
        <Link className="help-card-more" to={href}>ادامهٔ مطلب<Icon name="arrow" size={18} /></Link>
      </div>
    </div>
  </article>;
}
