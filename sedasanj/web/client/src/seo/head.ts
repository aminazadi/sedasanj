import { DEFAULT_SITE_URL, headTags, type PageSeo } from "./siteSeo";

export function siteUrl(): string {
  const configured = typeof __SITE_URL__ === "string" ? __SITE_URL__ : "";
  return (configured || (typeof window !== "undefined" ? window.location.origin : DEFAULT_SITE_URL)).replace(/\/+$/, "");
}

/** Replaces the document title and every managed `data-seo` tag in <head>. */
export function applySeo(page: PageSeo): void {
  const base = siteUrl();
  document.title = page.title;
  document.head.querySelectorAll("[data-seo]").forEach((node) => { if (node.tagName !== "TITLE") node.remove(); });
  const title = document.head.querySelector("title");
  if (title) title.setAttribute("data-seo", "");
  for (const entry of headTags(page, base)) {
    if (entry.tag === "script") {
      const script = document.createElement("script");
      script.type = "application/ld+json";
      script.textContent = JSON.stringify(entry.json);
      script.setAttribute("data-seo", "");
      document.head.appendChild(script);
    } else {
      const element = document.createElement(entry.tag);
      for (const [key, value] of Object.entries(entry.attrs)) element.setAttribute(key, value);
      element.setAttribute("data-seo", "");
      document.head.appendChild(element);
    }
  }
}
