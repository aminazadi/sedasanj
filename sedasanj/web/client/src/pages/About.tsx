import { Link } from "react-router-dom";
import { Icon } from "../components/SiteIcon";
import PublicPageFrame from "../components/PublicPageFrame";
import { HeroArt, PageStatus, SafeLink } from "../components/SitePageParts";
import { RichTitle, useSitePage, type AboutContent } from "../lib/sitePages";

export default function About() {
  const { state, reload } = useSitePage<AboutContent>("about");
  if (state.status !== "ready") return <PublicPageFrame><PageStatus state={state.status} onRetry={reload}/></PublicPageFrame>;
  const page = state.content;
  return <PublicPageFrame>
    <main className="page-main">
      <section className="site-hero page-hero"><div className="site-container site-split">
        <div>
        <h1 className="site-hero-title page-title"><RichTitle text={page.hero_title}/></h1>
        <p>{page.hero_text}</p>
        </div>
        <HeroArt/>
      </div></section>

      <section className="site-section"><div className="site-container about-story">
        <h2><RichTitle text={page.story_title}/></h2>
        <div className="about-story-copy">{page.story_paragraphs.map((text, index) => <p key={index}>{text}</p>)}</div>
      </div></section>

      {page.values.length > 0 && <section className="site-section about-values"><div className="site-container">
        <h2>{page.values_title}</h2>
        <div className="site-benefits">{page.values.map((value, index) => <article key={index}>{value.icon && <Icon name={value.icon} size={32}/>}<h3>{value.title}</h3><p>{value.text}</p></article>)}</div>
      </div></section>}

      <section className="site-cta"><div className="site-container">
        <h2><RichTitle text={page.outcome_title}/></h2>
        {page.outcome_text && <p>{page.outcome_text}</p>}
        {page.outcome_button && (page.outcome_link ? <SafeLink className="site-button" href={page.outcome_link}>{page.outcome_button}</SafeLink> : <Link className="site-button" to="/contact">{page.outcome_button}</Link>)}
      </div></section>
    </main>
  </PublicPageFrame>;
}
