import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import http from "node:http";
import path from "node:path";

const root = path.resolve(process.env.STATIC_ROOT || "/app/dist");
const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".mp3": "audio/mpeg",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".xml": "application/xml; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
};

// ---- Security headers (WSTG-CONF-07/14, CLNT-09) ---------------------------------------------
// One server image serves both panels; WEB_APP selects the profile. CSP_MEDIA_ORIGINS lists the
// object-storage origin(s) that serve call audio (presigned URLs) so the player may fetch them.
const WEB_APP = process.env.WEB_APP === "admin" ? "admin" : "client";
const SAFE_ORIGIN = /^https:\/\/[a-z0-9.-]+(:\d{1,5})?$/i;
const mediaOrigins = (process.env.CSP_MEDIA_ORIGINS || "").split(/\s+/).filter((origin) => SAFE_ORIGIN.test(origin));
const EMBED_FRAMES = "https://www.youtube-nocookie.com https://www.aparat.com";
const SAFE_HOST = /^[a-z0-9.-]+(:\d{1,5})?$/i;

function contentSecurityPolicy(request) {
  const override = process.env.CONTENT_SECURITY_POLICY;
  if (override) return override;
  const media = mediaOrigins.join(" ");
  const forwardedHost = String(request.headers["x-forwarded-host"] || request.headers.host || "").split(",")[0].trim();
  const socketOrigin = SAFE_HOST.test(forwardedHost) ? `wss://${forwardedHost}` : "";
  const directives = WEB_APP === "admin"
    ? {
        "default-src": "'self'",
        "script-src": "'self'",
        "style-src": "'self' 'unsafe-inline'",
        "img-src": "'self' data: blob:",
        "font-src": "'self' data:",
        "media-src": `'self' blob: ${media}`,
        "connect-src": `'self' ${socketOrigin} ${media}`,
        "frame-src": EMBED_FRAMES,
        "object-src": "'none'",
        "base-uri": "'none'",
        "form-action": "'self'",
        "frame-ancestors": "'none'",
      }
    : {
        "default-src": "'self'",
        // Admin-authored trust seals (enamad etc.) run in a sandboxed srcdoc iframe that inherits
        // this policy, so third-party https scripts stay allowed; inline scripts remain blocked.
        "script-src": "'self' https:",
        "style-src": "'self' 'unsafe-inline'",
        "img-src": "'self' data: blob: https:",
        "font-src": "'self' data:",
        "media-src": `'self' blob: ${media}`,
        "connect-src": `'self' ${socketOrigin} ${media}`,
        "frame-src": EMBED_FRAMES,
        "object-src": "'none'",
        "base-uri": "'none'",
        // Bank gateways receive an auto-submitted POST form (see client/src/lib/payment.ts).
        "form-action": "'self' https:",
        "frame-ancestors": "'self'",
      };
  return Object.entries(directives).map(([name, value]) => `${name} ${value.replace(/\s+/g, " ").trim()}`).join("; ");
}

/** Headers for every response; the page-level ones (CSP, framing) only apply to HTML/static. */
function applySecurityHeaders(request, response, { page }) {
  response.setHeader("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");
  if (!page) return;
  const microphone = WEB_APP === "client" ? "(self)" : "()";
  response.setHeader("Permissions-Policy", `camera=(), geolocation=(), payment=(), usb=(), microphone=${microphone}`);
  response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  response.setHeader("X-Frame-Options", WEB_APP === "admin" ? "DENY" : "SAMEORIGIN");
  const header = process.env.CSP_REPORT_ONLY === "1" ? "Content-Security-Policy-Report-Only" : "Content-Security-Policy";
  response.setHeader(header, contentSecurityPolicy(request));
}

// APK uploads (Jalase-Negar releases) may be large; everything else keeps the API's own limits.
const APK_UPLOAD_PATH = "/v1/admin/jalase-negar/releases";
const APK_UPLOAD_LIMIT = (Number(process.env.MAX_JALASE_NEGAR_APK_BYTES) || 200 * 1024 * 1024) + 1024 * 1024;

function rejectTooLarge(response) {
  const body = JSON.stringify({ error: { code: "archive_too_large", message: "the APK is larger than the allowed size; shrink the build", retryable: false } });
  response.writeHead(413, { "content-type": "application/json", "content-length": Buffer.byteLength(body), connection: "close" });
  response.end(body);
}

function proxyApi(request, response) {
  const isApkUpload = request.method === "POST" && request.url.split("?")[0] === APK_UPLOAD_PATH;
  if (isApkUpload && Number(request.headers["content-length"]) > APK_UPLOAD_LIMIT) {
    request.resume();
    return rejectTooLarge(response);
  }
  const headers = { ...request.headers };
  headers.host = request.headers.host;
  headers["x-real-ip"] = request.socket.remoteAddress;
  headers["x-forwarded-for"] = [request.headers["x-forwarded-for"], request.socket.remoteAddress]
    .filter(Boolean)
    .join(", ");
  headers["x-forwarded-host"] = request.headers.host;
  headers["x-forwarded-proto"] = request.headers["x-forwarded-proto"] || "http";

  const upstream = http.request({
    hostname: "api",
    port: 8000,
    path: request.url,
    method: request.method,
    headers,
    timeout: 3_600_000,
  }, (upstreamResponse) => {
    response.writeHead(upstreamResponse.statusCode, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  upstream.on("error", () => {
    if (!response.headersSent) response.writeHead(502);
    response.end();
  });
  request.on("aborted", () => upstream.destroy());
  if (isApkUpload) {
    // Chunked bodies carry no Content-Length, so count what actually flows through.
    let received = 0;
    request.on("data", (chunk) => {
      received += chunk.length;
      if (received > APK_UPLOAD_LIMIT && !response.headersSent) {
        upstream.destroy();
        rejectTooLarge(response);
        request.destroy();
      }
    });
  }
  request.pipe(upstream);
}


const SLUG = /^[a-z0-9][a-z0-9-]{0,119}$/;
const NOINDEX = { "X-Robots-Tag": "noindex, nofollow" };
const apiCache = new Map();

function apiGet(apiPath) {
  return new Promise((resolve) => {
    const upstream = http.request({ hostname: "api", port: 8000, path: apiPath, method: "GET", timeout: 5000, headers: { accept: "application/json" } }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        try { resolve({ status: res.statusCode, body: JSON.parse(Buffer.concat(chunks).toString("utf8")) }); }
        catch { resolve({ status: res.statusCode, body: null }); }
      });
    });
    upstream.on("timeout", () => upstream.destroy());
    upstream.on("error", () => resolve({ status: 0, body: null }));
    upstream.end();
  });
}

async function cached(key, ttlMs, load) {
  const hit = apiCache.get(key);
  if (hit && hit.expires > Date.now()) return hit.value;
  const value = await load();
  if (value.status !== 0) {
    if (apiCache.size > 1000) apiCache.clear();
    apiCache.set(key, { value, expires: Date.now() + ttlMs });
  }
  return value;
}

async function readManifest() {
  try { return JSON.parse(await readFile(path.join(root, "seo-routes.json"), "utf8")); } catch { return null; }
}

function sendHtml(request, response, status, body, extra = {}) {
  const data = Buffer.from(body);
  response.writeHead(status, { "Content-Type": mimeTypes[".html"], "Content-Length": data.length, "Cache-Control": "no-cache", ...extra });
  response.end(request.method === "HEAD" ? undefined : data);
}

const xmlEscape = (value) => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** sitemap.xml = hard-coded public routes (built) + every published help article (live from the API). */
async function sitemap(request, response) {
  const manifest = await readManifest();
  if (!manifest) { response.writeHead(404).end(); return; }
  const entries = [...manifest.entries];
  const articles = await cached("sitemap", 3_600_000, async () => {
    const items = [];
    for (let offset = 0; offset < 5000; offset += 100) {
      const page = await apiGet(`/v1/help/articles?limit=100&offset=${offset}`);
      if (page.status !== 200 || !page.body) return { status: items.length ? 200 : 0, body: items };
      items.push(...page.body.items);
      if (items.length >= page.body.total || page.body.items.length === 0) break;
    }
    return { status: 200, body: items };
  });
  for (const item of Array.isArray(articles.body) ? articles.body : []) {
    if (!SLUG.test(item.slug)) continue;
    entries.push({ path: `/help/${item.slug}`, lastmod: String(item.updated_at || item.published_at || "").slice(0, 10) || manifest.entries[0].lastmod, changefreq: "monthly", priority: 0.6 });
  }
  const base = manifest.siteUrl.replace(/\/+$/, "");
  const rows = entries.map((entry) => `  <url>\n    <loc>${xmlEscape(entry.path === "/" ? `${base}/` : `${base}${entry.path}`)}</loc>\n    <lastmod>${xmlEscape(entry.lastmod)}</lastmod>\n    <changefreq>${xmlEscape(entry.changefreq)}</changefreq>\n    <priority>${Number(entry.priority).toFixed(1)}</priority>\n  </url>`);
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${rows.join("\n")}\n</urlset>\n`;
  const data = Buffer.from(xml);
  response.writeHead(200, { "Content-Type": mimeTypes[".xml"], "Content-Length": data.length, "Cache-Control": "public, max-age=3600" });
  response.end(request.method === "HEAD" ? undefined : data);
}

const htmlEscape = (value) => String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const jsonEscape = (value) => JSON.stringify(String(value)).slice(1, -1).replace(/</g, "\\u003c");

function fillArticle(template, tokens, values) {
  const substitute = (text, escape) => Object.entries(tokens).reduce((out, [key, token]) => out.split(token).join(escape(values[key])), text);
  return template.split(/(<script type="application\/ld\+json"[^>]*>[\s\S]*?<\/script>)/)
    .map((part, index) => substitute(part, index % 2 ? jsonEscape : htmlEscape)).join("");
}

/** /help/<slug>: prerender the article's own title, description, canonical and JSON-LD into the shell. */
async function helpArticle(request, response, slug) {
  const manifest = await readManifest();
  const shell = path.join(root, "_seo", "private.html");
  if (!manifest || !SLUG.test(slug)) return sendHtml(request, response, 404, await readFile(shell, "utf8"), NOINDEX);
  const result = await cached(`article:${slug}`, 300_000, () => apiGet(`/v1/help/articles/${slug}`));
  if (result.status === 404) return sendHtml(request, response, 404, await readFile(shell, "utf8"), NOINDEX);
  if (result.status !== 200 || !result.body) return sendHtml(request, response, 503, await readFile(shell, "utf8"), { ...NOINDEX, "Retry-After": "300" });
  const article = result.body;
  const summary = String(article.summary || "").trim().slice(0, 200)
    || `${article.title}؛ راهنمای گام‌به‌گام در مرکز راهنمای صداسنج برای نصب، اتصال و رفع خطا.`;
  const html = fillArticle(await readFile(path.join(root, "_seo", "article.html"), "utf8"), manifest.tokens, {
    slug: article.slug, title: article.title, summary,
    published: article.published_at || article.updated_at, modified: article.updated_at || article.published_at,
  });
  sendHtml(request, response, 200, html);
}

async function serveStatic(request, response, pathname) {
  const filePath = path.resolve(root, `.${pathname}`);
  if (filePath !== root && !filePath.startsWith(`${root}${path.sep}`)) {
    response.writeHead(400).end();
    return;
  }

  if (pathname === "/sitemap.xml") return sitemap(request, response);
  if (pathname.length > 1 && pathname.endsWith("/")) {
    const query = new URL(request.url, "http://localhost").search;
    response.writeHead(301, { Location: pathname.replace(/\/+$/, "") + query }).end();
    return;
  }
  const article = /^\/help\/([^/]+)$/.exec(pathname);
  if (article && !path.extname(pathname)) {
    try { await stat(path.join(root, "_seo", "article.html")); return helpArticle(request, response, article[1]); } catch { /* not an SEO build */ }
  }

  let selectedPath = filePath;
  let fileInfo;
  let extraHeaders = {};
  try {
    fileInfo = await stat(selectedPath);
    if (fileInfo.isDirectory()) {
      selectedPath = path.join(selectedPath, "index.html");
      fileInfo = await stat(selectedPath);
    }
    if (!fileInfo.isFile()) throw new Error("Not a file");
  } catch {
    if (pathname.startsWith("/assets/") || path.extname(pathname)) {
      response.writeHead(404).end();
      return;
    }
    // Logged-in app routes and unknown URLs: the SPA shell, never indexed.
    selectedPath = path.join(root, "_seo", "private.html");
    try { fileInfo = await stat(selectedPath); } catch { selectedPath = path.join(root, "index.html"); fileInfo = await stat(selectedPath); }
    extraHeaders = NOINDEX;
  }

  const extension = path.extname(selectedPath);
  const headers = {
    "Content-Type": mimeTypes[extension] || "application/octet-stream",
    "Content-Length": fileInfo.size,
    "Cache-Control": pathname.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache",
    ...extraHeaders,
  };
  let range;
  if (pathname === "/quick-demo-instructions.mp3") {
    headers["Accept-Ranges"] = "bytes";
    const match = request.method === "GET" && !request.headers["if-range"]
      && /^bytes=(\d*)-(\d*)$/i.exec(request.headers.range || "");
    if (match && (match[1] || match[2])) {
      const start = match[1] ? Number(match[1]) : Math.max(fileInfo.size - Number(match[2]), 0);
      const end = match[1] && match[2] ? Math.min(Number(match[2]), fileInfo.size - 1) : fileInfo.size - 1;
      if (start > end) {
        response.writeHead(416, { ...headers, "Content-Length": 0, "Content-Range": `bytes */${fileInfo.size}` }).end();
        return;
      }
      range = { start, end };
      headers["Content-Range"] = `bytes ${start}-${end}/${fileInfo.size}`;
      headers["Content-Length"] = end - start + 1;
    }
  }
  response.writeHead(range ? 206 : 200, headers);
  if (request.method === "HEAD") response.end();
  else createReadStream(selectedPath, range).pipe(response);
}

// The archive endpoint counts streamed bytes in the API. Allow large uploads on slow links.
const server = http.createServer({ requestTimeout: 7_200_000 }, async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname.startsWith("/v1/") || pathname === "/socket.io" || pathname.startsWith("/socket.io/")) {
      applySecurityHeaders(request, response, { page: false });
      proxyApi(request, response);
    } else if (request.method === "GET" || request.method === "HEAD") {
      applySecurityHeaders(request, response, { page: true });
      await serveStatic(request, response, decodeURIComponent(pathname));
    } else {
      applySecurityHeaders(request, response, { page: false });
      response.writeHead(405).end();
    }
  } catch {
    if (!response.headersSent) response.writeHead(500);
    response.end();
  }
});

server.on("upgrade", (request, clientSocket, head) => {
  if (!new URL(request.url, "http://localhost").pathname.startsWith("/socket.io/")) {
    clientSocket.destroy();
    return;
  }
  const upstream = http.request({
    hostname: "api",
    port: 8000,
    path: request.url,
    headers: request.headers,
  });
  upstream.on("upgrade", (response, upstreamSocket, upstreamHead) => {
    const lines = [`HTTP/${response.httpVersion} ${response.statusCode} ${response.statusMessage}`];
    for (const [name, value] of Object.entries(response.headers)) {
      if (Array.isArray(value)) value.forEach((entry) => lines.push(`${name}: ${entry}`));
      else if (value !== undefined) lines.push(`${name}: ${value}`);
    }
    clientSocket.write(`${lines.join("\r\n")}\r\n\r\n`);
    if (head.length) upstreamSocket.write(head);
    if (upstreamHead.length) clientSocket.write(upstreamHead);
    upstreamSocket.pipe(clientSocket);
    clientSocket.pipe(upstreamSocket);
    clientSocket.on("error", () => upstreamSocket.destroy());
    upstreamSocket.on("error", () => clientSocket.destroy());
  });
  upstream.on("error", () => clientSocket.destroy());
  clientSocket.on("error", () => upstream.destroy());
  upstream.end();
});

// Slowloris guard: headers must arrive quickly; long uploads are still bounded by requestTimeout.
server.headersTimeout = 30_000;
server.maxConnections = Number(process.env.MAX_CONNECTIONS) || 2000;

server.listen(Number(process.env.PORT || 80), "0.0.0.0");
