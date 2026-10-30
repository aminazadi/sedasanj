/**
 * Hard-coded SEO source of truth for every public page.
 *
 * Pure data and pure functions (no DOM, no Vite env) so the same module drives the runtime head
 * updates, the build-time prerendered HTML, `sitemap.xml` and `robots.txt`.
 * Strategy and keyword research notes: docs/seo.md.
 */

export const SITE_NAME = "صداسنج";
export const SITE_NAME_LATIN = "SedaSanj";
export const SITE_LOCALE = "fa_IR";
export const SITE_LANG = "fa-IR";
export const DEFAULT_SITE_URL = "https://sedasanj.ir";
export const OG_IMAGE = { path: "/og-image.jpg", width: 1200, height: 630, type: "image/jpeg", alt: "تحلیل هوشمند مکالمات مرکز تماس با صداسنج" };
export const LOGO_PATH = "/logo.svg";

/** Bump `lastmod` on a route only when its visible content really changed. */
export type RouteKind = "home" | "about" | "contact" | "help" | "legal" | "auth" | "demo";
export type ChangeFreq = "daily" | "weekly" | "monthly" | "yearly";

export interface SeoRoute {
  path: string;
  kind: RouteKind;
  title: string;
  description: string;
  keywords: string[];
  /** Short breadcrumb label. */
  crumb: string;
  /** Visible heading repeated in the no-JavaScript fallback. */
  h1: string;
  index: boolean;
  changefreq: ChangeFreq;
  priority: number;
  lastmod: string;
}

export const CORE_KEYWORDS = [
  "تحلیل مکالمات فارسی",
  "تحلیل تماس تلفنی",
  "تبدیل گفتار به متن فارسی",
  "تشخیص گفتار فارسی",
  "رونویسی مکالمات تلفنی",
  "سنجش کیفیت تماس",
  "ارزیابی کیفیت اپراتور",
  "نرم‌افزار کال سنتر",
  "مرکز تماس هوشمند",
  "تحلیل احساس مشتری",
  "خلاصه‌سازی مکالمه",
  "هوش مصنوعی مرکز تماس",
  "ماژول FreePBX",
  "ضبط و تحلیل مکالمات",
  "گفتار به متن تماس",
  "صداسنج",
];

export const SEO_ROUTES: SeoRoute[] = [
  {
    path: "/", kind: "home", crumb: "صفحه اصلی", index: true, changefreq: "weekly", priority: 1.0, lastmod: "2026-10-30",
    title: "صداسنج | تحلیل هوشمند مکالمات و کیفیت تماس‌ها در مرکز تماس",
    h1: "همه تماس‌های مشتریان را بشنوید؛ بدون گوش دادن به ساعت‌ها فایل صوتی",
    description: "صداسنج تماس‌های فارسی مرکز تماس و FreePBX را به متن، خلاصه، تحلیل احساس و امتیاز کیفیت اپراتور تبدیل می‌کند. تست رایگان، نصب ساده، گزارش‌های مدیریتی.",
    keywords: [
      ...CORE_KEYWORDS,
      "نرم‌افزار تحلیل مکالمات کال سنتر",
      "مانیتورینگ کیفیت مرکز تماس",
      "امتیازدهی خودکار به تماس اپراتور",
      "تحلیل احساس و لحن مشتری",
      "استخراج پیگیری از تماس",
      "ایزابل و الستیکس و ویپ",
      "speech analytics فارسی",
      "call center analytics",
    ],
  },
  {
    path: "/about", kind: "about", crumb: "درباره ما", index: true, changefreq: "monthly", priority: 0.7, lastmod: "2026-10-30",
    title: "درباره صداسنج | مأموریت، تیم و ارزش‌های ما",
    h1: "درباره صداسنج",
    description: "با صداسنج و مأموریت آن آشنا شوید: کمک به سازمان‌ها برای شنیدن همه تماس‌های مشتریان، بهبود کیفیت پاسخ‌گویی و تصمیم‌گیری بر پایه داده‌های واقعی مکالمه.",
    keywords: ["درباره صداسنج", "شرکت تحلیل مکالمات فارسی", "تیم صداسنج", "هوش مصنوعی فارسی", "تحلیل گفتار فارسی", "بهبود تجربه مشتری", "کیفیت پاسخ‌گویی مرکز تماس"],
  },
  {
    path: "/contact", kind: "contact", crumb: "تماس با ما", index: true, changefreq: "monthly", priority: 0.7, lastmod: "2026-10-30",
    title: "تماس با صداسنج | مشاوره، پشتیبانی و درخواست دمو",
    h1: "تماس با صداسنج",
    description: "برای مشاوره، دموی رایگان، پشتیبانی فنی و راه‌اندازی صداسنج در مرکز تماس خود فرم تماس را پر کنید یا مستقیم با تیم فروش و پشتیبانی صداسنج صحبت کنید.",
    keywords: ["تماس با صداسنج", "مشاوره تحلیل مکالمات", "درخواست دمو صداسنج", "پشتیبانی صداسنج", "شماره تماس صداسنج", "خرید نرم‌افزار تحلیل تماس", "راه‌اندازی تحلیل مکالمات"],
  },
  {
    path: "/help", kind: "help", crumb: "مرکز راهنما", index: true, changefreq: "weekly", priority: 0.8, lastmod: "2026-10-30",
    title: "مرکز راهنمای صداسنج | نصب ماژول FreePBX و رفع خطا",
    h1: "مرکز راهنمای صداسنج",
    description: "آموزش نصب ماژول FreePBX صداسنج، اتصال کلید API، رفع خطا با جست‌وجوی کد خطا (مثل SS-UPL-0401) و پاسخ پرسش‌های متداول درباره تحلیل مکالمات.",
    keywords: ["راهنمای صداسنج", "نصب ماژول FreePBX", "آموزش FreePBX فارسی", "کلید API صداسنج", "کد خطا صداسنج", "رفع خطای آپلود تماس", "ضبط مکالمات الستیکس", "آموزش تحلیل مکالمات", "پرسش‌های متداول صداسنج"],
  },
  {
    path: "/quick-demo", kind: "demo", crumb: "تست رایگان", index: true, changefreq: "monthly", priority: 0.8, lastmod: "2026-10-30",
    title: "تست رایگان صداسنج | تحلیل یک تماس واقعی در چند دقیقه",
    h1: "تست رایگان تحلیل مکالمه",
    description: "یک فایل صوتی یا مکالمه نمونه را بدون ثبت‌نام طولانی امتحان کنید و متن، خلاصه، لحن مشتری و امتیاز کیفیت تماس را در چند دقیقه ببینید.",
    keywords: ["تست رایگان تحلیل مکالمه", "دمو صداسنج", "تبدیل فایل صوتی به متن فارسی", "تحلیل فایل صوتی تماس", "آزمایش رایگان گفتار به متن", "نمونه تحلیل تماس"],
  },
  {
    path: "/signup", kind: "auth", crumb: "ثبت‌نام", index: true, changefreq: "monthly", priority: 0.6, lastmod: "2026-10-30",
    title: "ثبت‌نام در صداسنج | شروع تحلیل هوشمند تماس‌ها",
    h1: "ثبت‌نام در صداسنج",
    description: "با شماره موبایل در صداسنج ثبت‌نام کنید، پلن مناسب سازمان خود را انتخاب کنید و ماژول FreePBX را برای شروع تحلیل خودکار تماس‌ها نصب کنید.",
    keywords: ["ثبت‌نام صداسنج", "خرید اشتراک تحلیل مکالمات", "پلن‌های صداسنج", "تعرفه تحلیل تماس", "قیمت نرم‌افزار تحلیل مکالمات", "پلن رایگان تحلیل مکالمه"],
  },
  {
    path: "/login", kind: "auth", crumb: "ورود", index: false, changefreq: "yearly", priority: 0.1, lastmod: "2026-10-30",
    title: "ورود به پنل صداسنج", h1: "ورود به پنل صداسنج",
    description: "ورود به پنل مدیریتی صداسنج برای مشاهده تماس‌ها، تحلیل‌ها و گزارش‌های کیفیت.",
    keywords: ["ورود به صداسنج", "پنل صداسنج"],
  },
  {
    path: "/terms", kind: "legal", crumb: "قوانین استفاده", index: true, changefreq: "yearly", priority: 0.3, lastmod: "2026-10-30",
    title: "قوانین و شرایط استفاده از صداسنج", h1: "قوانین و شرایط استفاده",
    description: "شرایط استفاده از خدمات صداسنج، حقوق و مسئولیت‌های کاربران، پلن‌ها، پرداخت و محدودیت‌های سرویس تحلیل مکالمات را مطالعه کنید.",
    keywords: ["قوانین صداسنج", "شرایط استفاده از خدمات", "قرارداد استفاده از نرم‌افزار", "قوانین سرویس تحلیل مکالمات", "مسئولیت کاربران صداسنج"],
  },
  {
    path: "/privacy", kind: "legal", crumb: "حریم خصوصی", index: true, changefreq: "yearly", priority: 0.3, lastmod: "2026-10-30",
    title: "حریم خصوصی و امنیت داده‌ها در صداسنج", h1: "حریم خصوصی و امنیت داده‌ها",
    description: "بدانید صداسنج چه داده‌هایی را از مکالمات و حساب کاربری شما نگهداری می‌کند، چگونه از آن‌ها محافظت می‌کند و چه کنترل‌هایی در اختیار شماست.",
    keywords: ["حریم خصوصی صداسنج", "امنیت داده مکالمات", "حفاظت از اطلاعات تماس", "سیاست نگهداری داده", "امنیت تحلیل مکالمات", "محرمانگی مکالمات مشتریان"],
  },
  {
    path: "/cancellation", kind: "legal", crumb: "لغو اشتراک", index: true, changefreq: "yearly", priority: 0.3, lastmod: "2026-10-30",
    title: "لغو اشتراک و بازگشت وجه در صداسنج", h1: "لغو اشتراک و بازگشت وجه",
    description: "شرایط لغو اشتراک، تمدید، تغییر پلن و بازگشت وجه در صداسنج را به‌صورت شفاف بخوانید و بدانید در هر مرحله چه اقدامی لازم است.",
    keywords: ["لغو اشتراک صداسنج", "بازگشت وجه", "تمدید اشتراک", "تغییر پلن", "قوانین لغو سرویس", "شرایط استرداد وجه صداسنج"],
  },
];

/**
 * Logged-in application paths. They are never indexed (robots.txt disallow, `noindex` header and
 * meta tag). Keep in sync with the routes in App.tsx.
 */
export const PRIVATE_PATHS = [
  "/calls", "/contacts", "/tasks", "/assistant", "/scheduled-reports", "/operator-scores", "/profile",
  "/account", "/account-settings", "/kpi-settings", "/checkout", "/payment-result", "/install",
  "/module-changelog", "/freepbx-servers", "/api-docs", "/demo",
];

const PRIVATE_TITLE = "پنل صداسنج";

export function normalizePath(path: string): string {
  const clean = path.split(/[?#]/)[0] || "/";
  return clean.length > 1 ? clean.replace(/\/+$/, "") : "/";
}

export function findRoute(path: string): SeoRoute | undefined {
  const target = normalizePath(path);
  return SEO_ROUTES.find((route) => route.path === target);
}

export function isPrivatePath(path: string): boolean {
  const target = normalizePath(path);
  return PRIVATE_PATHS.some((entry) => target === entry || target.startsWith(`${entry}/`));
}

export function absoluteUrl(siteUrl: string, path: string): string {
  const base = siteUrl.replace(/\/+$/, "");
  return path === "/" ? `${base}/` : `${base}${path}`;
}

export interface PageSeo {
  path: string;
  title: string;
  description: string;
  keywords: string[];
  noindex: boolean;
  ogType: "website" | "article";
  jsonLd: Array<Record<string, unknown>>;
  article?: { published?: string; modified?: string };
}

const SCHEMA_TYPE: Record<RouteKind, string> = {
  home: "WebPage", about: "AboutPage", contact: "ContactPage", help: "CollectionPage",
  legal: "WebPage", auth: "WebPage", demo: "WebPage",
};

function organization(siteUrl: string): Record<string, unknown> {
  return {
    "@type": "Organization",
    "@id": `${siteUrl}/#organization`,
    name: SITE_NAME,
    alternateName: SITE_NAME_LATIN,
    url: `${siteUrl}/`,
    logo: { "@type": "ImageObject", url: `${siteUrl}${LOGO_PATH}` },
    areaServed: { "@type": "Country", name: "ایران" },
    contactPoint: [{
      "@type": "ContactPoint",
      contactType: "sales",
      availableLanguage: ["fa"],
      areaServed: "IR",
      url: `${siteUrl}/contact`,
    }],
  };
}

function website(siteUrl: string): Record<string, unknown> {
  return {
    "@type": "WebSite",
    "@id": `${siteUrl}/#website`,
    url: `${siteUrl}/`,
    name: SITE_NAME,
    alternateName: SITE_NAME_LATIN,
    inLanguage: SITE_LANG,
    publisher: { "@id": `${siteUrl}/#organization` },
  };
}

function software(siteUrl: string): Record<string, unknown> {
  return {
    "@type": "SoftwareApplication",
    "@id": `${siteUrl}/#software`,
    name: SITE_NAME,
    alternateName: SITE_NAME_LATIN,
    url: `${siteUrl}/`,
    applicationCategory: "BusinessApplication",
    applicationSubCategory: "Call center analytics",
    operatingSystem: "Web",
    inLanguage: SITE_LANG,
    description: "سامانه تحلیل مکالمات فارسی: تبدیل گفتار به متن، خلاصه‌سازی، تحلیل احساس، ارزیابی کیفیت اپراتور و استخراج پیگیری‌ها از تماس‌های مرکز تماس و FreePBX.",
    featureList: [
      "تبدیل گفتار تماس به متن فارسی",
      "خلاصه و نکات کلیدی هر مکالمه",
      "تحلیل موضوع، احساس و نتیجه تماس",
      "امتیازدهی خودکار کیفیت اپراتورها",
      "استخراج و مدیریت پیگیری‌ها",
      "داشبورد و گزارش‌های مدیریتی",
      "دستیار هوشمند سازمان",
      "ماژول نصب آسان برای FreePBX",
    ],
    offers: { "@type": "Offer", price: "0", priceCurrency: "IRR", description: "تست رایگان و پلن آزمایشی" },
    publisher: { "@id": `${siteUrl}/#organization` },
  };
}

function breadcrumb(siteUrl: string, items: Array<{ name: string; path: string }>): Record<string, unknown> {
  return {
    "@type": "BreadcrumbList",
    itemListElement: items.map((item, index) => ({
      "@type": "ListItem", position: index + 1, name: item.name, item: absoluteUrl(siteUrl, item.path),
    })),
  };
}

export function routeSeo(route: SeoRoute, siteUrl: string): PageSeo {
  const url = absoluteUrl(siteUrl, route.path);
  const graph: Array<Record<string, unknown>> = [];
  if (route.kind === "home") graph.push(organization(siteUrl), website(siteUrl), software(siteUrl));
  const page: Record<string, unknown> = {
    "@type": SCHEMA_TYPE[route.kind], "@id": `${url}#webpage`, url, name: route.title,
    description: route.description, inLanguage: SITE_LANG, isPartOf: { "@id": `${siteUrl}/#website` },
    primaryImageOfPage: { "@type": "ImageObject", url: `${siteUrl}${OG_IMAGE.path}` },
  };
  if (route.kind === "home") page.about = { "@id": `${siteUrl}/#software` };
  graph.push(page);
  if (route.path !== "/") graph.push(breadcrumb(siteUrl, [{ name: "صفحه اصلی", path: "/" }, { name: route.crumb, path: route.path }]));
  return {
    path: route.path, title: route.title, description: route.description, keywords: route.keywords,
    noindex: !route.index, ogType: "website", jsonLd: [{ "@context": "https://schema.org", "@graph": graph }],
  };
}

export function privateSeo(path: string): PageSeo {
  return { path: normalizePath(path), title: PRIVATE_TITLE, description: "", keywords: [], noindex: true, ogType: "website", jsonLd: [] };
}

/** Help article: `articleSeo` is also used with placeholder values to build the server template. */
export function articleSeo(
  siteUrl: string,
  article: { slug: string; title: string; summary: string; published?: string; modified?: string },
): PageSeo {
  const path = `/help/${article.slug}`;
  const url = absoluteUrl(siteUrl, path);
  const title = `${article.title} | راهنمای ${SITE_NAME}`;
  const description = article.summary.trim() || `${article.title}؛ راهنمای گام‌به‌گام در مرکز راهنمای ${SITE_NAME} برای نصب، اتصال و رفع خطا.`;
  const entry: Record<string, unknown> = {
    "@type": "TechArticle", "@id": `${url}#article`, headline: article.title, description, url,
    inLanguage: SITE_LANG, mainEntityOfPage: url,
    image: `${siteUrl}${OG_IMAGE.path}`,
    author: { "@id": `${siteUrl}/#organization` }, publisher: { "@id": `${siteUrl}/#organization` },
  };
  if (article.published) entry.datePublished = article.published;
  if (article.modified || article.published) entry.dateModified = article.modified || article.published;
  return {
    path, title, description: description.slice(0, 200), noindex: false, ogType: "article",
    keywords: [article.title, "راهنمای صداسنج", "نصب ماژول FreePBX", "رفع خطا", ...CORE_KEYWORDS.slice(0, 4)],
    article: { published: article.published, modified: article.modified || article.published },
    jsonLd: [{
      "@context": "https://schema.org",
      "@graph": [entry, breadcrumb(siteUrl, [{ name: "صفحه اصلی", path: "/" }, { name: "مرکز راهنما", path: "/help" }, { name: article.title, path }])],
    }],
  };
}

export type HeadTag =
  | { tag: "meta"; attrs: Record<string, string> }
  | { tag: "link"; attrs: Record<string, string> }
  | { tag: "script"; json: unknown };

const ROBOTS_INDEX = "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1";
const ROBOTS_NOINDEX = "noindex, nofollow";

/** Every tag below is marked `data-seo` so it can be replaced on client-side navigation. */
export function headTags(page: PageSeo, siteUrl: string): HeadTag[] {
  const url = absoluteUrl(siteUrl, page.path);
  const image = `${siteUrl}${OG_IMAGE.path}`;
  const tags: HeadTag[] = [];
  const meta = (key: "name" | "property", name: string, content: string) => tags.push({ tag: "meta", attrs: { [key]: name, content } });
  if (page.description) meta("name", "description", page.description);
  if (page.keywords.length) meta("name", "keywords", page.keywords.join("، "));
  meta("name", "robots", page.noindex ? ROBOTS_NOINDEX : ROBOTS_INDEX);
  if (page.noindex) return tags;
  tags.push({ tag: "link", attrs: { rel: "canonical", href: url } });
  tags.push({ tag: "link", attrs: { rel: "alternate", hreflang: "fa-IR", href: url } });
  tags.push({ tag: "link", attrs: { rel: "alternate", hreflang: "x-default", href: url } });
  meta("property", "og:site_name", SITE_NAME);
  meta("property", "og:locale", SITE_LOCALE);
  meta("property", "og:type", page.ogType);
  meta("property", "og:title", page.title);
  meta("property", "og:description", page.description);
  meta("property", "og:url", url);
  meta("property", "og:image", image);
  meta("property", "og:image:type", OG_IMAGE.type);
  meta("property", "og:image:width", String(OG_IMAGE.width));
  meta("property", "og:image:height", String(OG_IMAGE.height));
  meta("property", "og:image:alt", OG_IMAGE.alt);
  if (page.article?.published) meta("property", "article:published_time", page.article.published);
  if (page.article?.modified) meta("property", "article:modified_time", page.article.modified);
  meta("name", "twitter:card", "summary_large_image");
  meta("name", "twitter:title", page.title);
  meta("name", "twitter:description", page.description);
  meta("name", "twitter:image", image);
  meta("name", "twitter:image:alt", OG_IMAGE.alt);
  for (const json of page.jsonLd) tags.push({ tag: "script", json });
  return tags;
}

export function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function jsonForScript(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c").replace(new RegExp("\\u2028", "g"), "\\u2028").replace(new RegExp("\\u2029", "g"), "\\u2029");
}

/** Static `<head>` fragment (title + tags) used for prerendered HTML. */
export function renderHead(page: PageSeo, siteUrl: string): string {
  const lines = [`<title data-seo>${escapeHtml(page.title)}</title>`];
  for (const entry of headTags(page, siteUrl)) {
    if (entry.tag === "script") {
      lines.push(`<script type="application/ld+json" data-seo>${jsonForScript(entry.json)}</script>`);
    } else {
      const attrs = Object.entries(entry.attrs).map(([key, value]) => `${key}="${escapeHtml(value)}"`).join(" ");
      lines.push(`<${entry.tag} ${attrs} data-seo />`);
    }
  }
  return lines.join("\n    ");
}

/** Content for crawlers that do not run JavaScript (inside <noscript>). */
export function renderNoscript(route: SeoRoute): string {
  const links = SEO_ROUTES.filter((entry) => entry.index).map((entry) => `<li><a href="${entry.path}">${escapeHtml(entry.crumb)}</a></li>`).join("");
  return `<noscript data-seo><main dir="rtl" lang="fa"><h1>${escapeHtml(route.h1)}</h1><p>${escapeHtml(route.description)}</p><nav aria-label="صفحات اصلی"><ul>${links}</ul></nav><p>برای استفاده از صداسنج جاوااسکریپت مرورگر را فعال کنید.</p></main></noscript>`;
}

export function robotsTxt(siteUrl: string): string {
  const disallow = PRIVATE_PATHS.map((entry) => `Disallow: ${entry}`);
  return [
    "# robots.txt — SedaSanj public site",
    "# /v1/ stays crawlable on purpose: public pages are rendered from /v1/site/pages and /v1/help.",
    "User-agent: *",
    "Allow: /",
    ...disallow,
    "Disallow: /socket.io/",
    "",
    `Sitemap: ${siteUrl}/sitemap.xml`,
    "",
  ].join("\n");
}

export interface SitemapEntry { path: string; lastmod: string; changefreq: ChangeFreq; priority: number }

export function sitemapXml(siteUrl: string, entries: SitemapEntry[]): string {
  const rows = entries.map((entry) => `  <url>\n    <loc>${escapeHtml(absoluteUrl(siteUrl, entry.path))}</loc>\n    <lastmod>${entry.lastmod}</lastmod>\n    <changefreq>${entry.changefreq}</changefreq>\n    <priority>${entry.priority.toFixed(1)}</priority>\n  </url>`);
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${rows.join("\n")}\n</urlset>\n`;
}

export function staticSitemapEntries(): SitemapEntry[] {
  return SEO_ROUTES.filter((route) => route.index).map(({ path, lastmod, changefreq, priority }) => ({ path, lastmod, changefreq, priority }));
}
