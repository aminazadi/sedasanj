import { useEffect } from "react";
import { applySeo, siteUrl } from "./head";
import { articleSeo, privateSeo } from "./siteSeo";

export interface ArticleMeta { slug: string; title: string; summary: string; published_at: string | null; updated_at?: string }

/** Help article metadata (title, description, canonical, TechArticle JSON-LD) once it has loaded. */
export function useArticleSeo(article: ArticleMeta | null, missing = false): void {
  useEffect(() => {
    if (missing) { applySeo(privateSeo(window.location.pathname)); return; }
    if (!article) return;
    applySeo(articleSeo(siteUrl(), {
      slug: article.slug, title: article.title, summary: article.summary,
      published: article.published_at ?? undefined, modified: article.updated_at ?? article.published_at ?? undefined,
    }));
  }, [article, missing]);
}
