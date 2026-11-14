import { useEffect, useRef, useState } from "react";
import ArticleCard, { type ArticleCardData } from "./ArticleCard";
import { Icon } from "./SiteIcon";

type Article = ArticleCardData;

export default function RelatedArticles({ items, title = "مقالات بیشتر" }: { items: Article[]; title?: string | null }) {
  const track = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);
  const [atEnd, setAtEnd] = useState(false);
  function updateEnd() {
    const container = track.current;
    if (container) setAtEnd(container.scrollWidth - container.clientWidth - Math.abs(container.scrollLeft) < 2);
  }
  useEffect(() => {
    const container = track.current;
    if (!container) return;
    const observer = new ResizeObserver(updateEnd);
    observer.observe(container);
    updateEnd();
    return () => observer.disconnect();
  }, [items]);
  function go(index: number) {
    const container = track.current;
    const card = container?.children[index];
    if (!container || !card) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    container.scrollBy({ left: card.getBoundingClientRect().right - container.getBoundingClientRect().right, behavior: reduced ? "auto" : "smooth" });
  }
  return <section className="related-articles" aria-label="مقالات بیشتر" aria-roledescription="کاروسل" dir="rtl">
    <div className="related-articles-heading">
      {title ? <h2>{title}</h2> : <span />}
      <div className="related-articles-controls">
        <button type="button" aria-label="مقالهٔ قبلی" disabled={active === 0} onClick={() => go(active - 1)}><Icon name="back" size={20} /></button>
        <button type="button" aria-label="مقالهٔ بعدی" disabled={atEnd} onClick={() => go(active + 1)}><Icon name="arrow" size={20} /></button>
      </div>
    </div>
    <div className="related-articles-track" ref={track} onScroll={() => {
      const container = track.current;
      if (!container) return;
      updateEnd();
      const right = container.getBoundingClientRect().right;
      let nearest = 0;
      let distance = Infinity;
      Array.from(container.children).forEach((card, index) => {
        const delta = Math.abs(card.getBoundingClientRect().right - right);
        if (delta < distance) { nearest = index; distance = delta; }
      });
      setActive(nearest);
    }}>
      {items.map((article, index) => <div className="related-article-slot" key={article.id} role="group" aria-label={`${index + 1} از ${items.length}`}>
        <ArticleCard article={article} />
      </div>)}
    </div>
  </section>;
}
