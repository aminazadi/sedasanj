import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Plugin } from "vite";
import {
  SEO_ROUTES, articleSeo, findRoute, privateSeo, renderHead, renderNoscript, robotsTxt, routeSeo, sitemapXml,
  staticSitemapEntries, type SeoRoute,
} from "../src/seo/siteSeo";

const HEAD_MARK = "<!--seo:head-->";
const NOSCRIPT_MARK = "<!--seo:noscript-->";
const BLOCK = /<!--seo:start-->[\s\S]*?<!--seo:end-->/;
const NOSCRIPT_BLOCK = /<!--seo:ns-start-->[\s\S]*?<!--seo:ns-end-->/;

/** Tokens the web server swaps for real help-article values (see deploy/web-server.mjs). */
export const ARTICLE_TOKENS = { slug: "__SEO_SLUG__", title: "__SEO_TITLE__", summary: "__SEO_SUMMARY__", published: "__SEO_PUBLISHED__", modified: "__SEO_MODIFIED__" };

function fill(html: string, head: string, noscript: string): string {
  return html
    .replace(BLOCK, () => `<!--seo:start-->\n    ${head}\n    <!--seo:end-->`)
    .replace(NOSCRIPT_BLOCK, () => `<!--seo:ns-start-->${noscript}<!--seo:ns-end-->`);
}

/**
 * Build-time SEO output: per-route prerendered head (so crawlers and link previews that do not run
 * JavaScript see real metadata), sitemap.xml, robots.txt and the routing manifest used by the
 * production web server.
 */
export default function seoPlugin(siteUrl: string): Plugin {
  let outDir = "dist";
  return {
    name: "sedasanj-seo",
    configResolved(config) { outDir = path.resolve(config.root, config.build.outDir); },
    transformIndexHtml(html) {
      const home = SEO_ROUTES[0];
      return html
        .replace(HEAD_MARK, `<!--seo:start-->\n    ${renderHead(routeSeo(home, siteUrl), siteUrl)}\n    <!--seo:end-->`)
        .replace(NOSCRIPT_MARK, `<!--seo:ns-start-->${renderNoscript(home)}<!--seo:ns-end-->`);
    },
    async closeBundle() {
      const template = await readFile(path.join(outDir, "index.html"), "utf8");
      const write = async (file: string, body: string) => {
        await mkdir(path.dirname(path.join(outDir, file)), { recursive: true });
        await writeFile(path.join(outDir, file), body);
      };
      const render = (page: ReturnType<typeof routeSeo>, route: SeoRoute) => fill(template, renderHead(page, siteUrl), renderNoscript(route));
      for (const route of SEO_ROUTES.filter((entry) => entry.path !== "/")) {
        await write(`${route.path.slice(1)}/index.html`, render(routeSeo(route, siteUrl), route));
      }
      const article = articleSeo(siteUrl, { slug: ARTICLE_TOKENS.slug, title: ARTICLE_TOKENS.title, summary: ARTICLE_TOKENS.summary, published: ARTICLE_TOKENS.published, modified: ARTICLE_TOKENS.modified });
      await write("_seo/article.html", fill(template, renderHead(article, siteUrl), renderNoscript(findRoute("/help") as SeoRoute)));
      await write("_seo/private.html", fill(template, renderHead(privateSeo("/"), siteUrl), ""));
      await write("robots.txt", robotsTxt(siteUrl));
      await write("sitemap.xml", sitemapXml(siteUrl, staticSitemapEntries()));
      await write("seo-routes.json", JSON.stringify({ siteUrl, tokens: ARTICLE_TOKENS, entries: staticSitemapEntries() }));
    },
  };
}
