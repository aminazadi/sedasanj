import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/seo/siteSeo.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
const seo = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const SITE = 'https://example.test';
const indexed = seo.SEO_ROUTES.filter((route) => route.index);

test('every indexable route has a unique, well-sized title and description', () => {
  assert.equal(new Set(indexed.map((route) => route.title)).size, indexed.length);
  assert.equal(new Set(indexed.map((route) => route.description)).size, indexed.length);
  for (const route of indexed) {
    assert.ok(route.title.length >= 20 && route.title.length <= 75, `${route.path} title length ${route.title.length}`);
    assert.ok(route.description.length >= 100 && route.description.length <= 200, `${route.path} description length ${route.description.length}`);
    assert.ok(route.keywords.length >= 5, `${route.path} keywords`);
    assert.ok(route.priority >= 0 && route.priority <= 1);
    assert.match(route.lastmod, /^\d{4}-\d{2}-\d{2}$/);
  }
});

test('route paths are unique, absolute and never private', () => {
  const paths = seo.SEO_ROUTES.map((route) => route.path);
  assert.equal(new Set(paths).size, paths.length);
  for (const route of seo.SEO_ROUTES) {
    assert.ok(route.path.startsWith('/'));
    if (route.path !== '/') assert.ok(!route.path.endsWith('/'));
    assert.equal(seo.isPrivatePath(route.path), false, route.path);
  }
});

test('indexable pages carry canonical, Open Graph, Twitter and parseable JSON-LD', () => {
  for (const route of indexed) {
    const html = seo.renderHead(seo.routeSeo(route, SITE), SITE);
    assert.ok(html.includes(`rel="canonical" href="${seo.absoluteUrl(SITE, route.path)}"`), route.path);
    for (const tag of ['og:title', 'og:description', 'og:url', 'og:image', 'twitter:card', 'index, follow']) assert.ok(html.includes(tag), `${route.path} ${tag}`);
    const raw = /<script type="application\/ld\+json" data-seo>(.*)<\/script>/s.exec(html)[1];
    const graph = JSON.parse(raw)['@graph'];
    assert.ok(graph.some((node) => node['@type'].endsWith('Page')));
    if (route.path !== '/') assert.ok(graph.some((node) => node['@type'] === 'BreadcrumbList'));
  }
});

test('home page declares organization, website and software application', () => {
  const [json] = seo.routeSeo(seo.SEO_ROUTES[0], SITE).jsonLd;
  const types = json['@graph'].map((node) => node['@type']);
  for (const type of ['Organization', 'WebSite', 'SoftwareApplication', 'WebPage']) assert.ok(types.includes(type), type);
});

test('private and noindex pages never expose a canonical or social tags', () => {
  const html = seo.renderHead(seo.privateSeo('/calls/1'), SITE);
  assert.ok(html.includes('noindex, nofollow'));
  assert.ok(!html.includes('canonical') && !html.includes('og:'));
  const login = seo.renderHead(seo.routeSeo(seo.findRoute('/login'), SITE), SITE);
  assert.ok(login.includes('noindex, nofollow') && !login.includes('canonical'));
});

test('article metadata escapes hostile titles in HTML and JSON-LD', () => {
  const page = seo.articleSeo(SITE, { slug: 'x', title: '</script><b>"hi"', summary: '', published: '2026-01-01T00:00:00Z' });
  const html = seo.renderHead(page, SITE);
  assert.ok(!html.includes('</script><b>'));
  assert.ok(html.includes('&lt;/script&gt;'));
  assert.ok(html.includes('\\u003c/script>'));
  assert.equal(page.ogType, 'article');
});

test('robots.txt keeps /v1/ crawlable, hides the app and points at the sitemap', () => {
  const robots = seo.robotsTxt(SITE);
  assert.ok(robots.includes(`Sitemap: ${SITE}/sitemap.xml`));
  assert.ok(!/Disallow: \/v1/.test(robots));
  for (const entry of seo.PRIVATE_PATHS) assert.ok(robots.includes(`Disallow: ${entry}`), entry);
});

test('sitemap lists exactly the indexable routes with absolute URLs', () => {
  const xml = seo.sitemapXml(SITE, seo.staticSitemapEntries());
  assert.equal((xml.match(/<url>/g) ?? []).length, indexed.length);
  assert.ok(xml.includes(`<loc>${SITE}/</loc>`) && !xml.includes('/login'));
});
