import PublicPageFrame from "../components/PublicPageFrame";
import { HeroArt, PageStatus } from "../components/SitePageParts";
import { Paragraphs, useSitePage, type LegalContent } from "../lib/sitePages";

export default function Legal({ slug }: { slug: "terms" | "privacy" | "cancellation" }) {
  const { state, reload } = useSitePage<LegalContent>(slug);
  if (state.status !== "ready") return <PublicPageFrame><PageStatus state={state.status} onRetry={reload}/></PublicPageFrame>;
  const page = state.content;
  return <PublicPageFrame>
    <main className="page-main">
      <section className="site-hero page-hero"><div className="site-container site-split">
        <div>
        <h1 className="site-hero-title page-title">{page.title}</h1>
        {page.intro && <p>{page.intro}</p>}
        {page.updated_label && <small className="legal-updated">{page.updated_label}</small>}
        </div>
        <HeroArt page="legal"/>
      </div></section>
      {page.sections.length > 0 && <section className="site-section"><div className="site-container legal-text">
        {page.sections.map((section, index) => <section key={index}><h2>{section.title}</h2><Paragraphs text={section.body}/></section>)}
      </div></section>}
    </main>
  </PublicPageFrame>;
}
