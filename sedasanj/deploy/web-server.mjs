import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import http from "node:http";
import path from "node:path";

const root = path.resolve(process.env.STATIC_ROOT || "/app/dist");
const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

function proxyApi(request, response) {
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
  request.pipe(upstream);
}

async function serveStatic(request, response, pathname) {
  const filePath = path.resolve(root, `.${pathname}`);
  if (filePath !== root && !filePath.startsWith(`${root}${path.sep}`)) {
    response.writeHead(400).end();
    return;
  }

  let selectedPath = filePath;
  let fileInfo;
  try {
    fileInfo = await stat(selectedPath);
    if (!fileInfo.isFile()) throw new Error("Not a file");
  } catch {
    if (pathname.startsWith("/assets/") || path.extname(pathname)) {
      response.writeHead(404).end();
      return;
    }
    selectedPath = path.join(root, "index.html");
    fileInfo = await stat(selectedPath);
  }

  const extension = path.extname(selectedPath);
  response.writeHead(200, {
    "Content-Type": mimeTypes[extension] || "application/octet-stream",
    "Content-Length": fileInfo.size,
    "Cache-Control": pathname.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache",
  });
  if (request.method === "HEAD") response.end();
  else createReadStream(selectedPath).pipe(response);
}

http.createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname.startsWith("/v1/")) {
      proxyApi(request, response);
    } else if (request.method === "GET" || request.method === "HEAD") {
      await serveStatic(request, response, decodeURIComponent(pathname));
    } else {
      response.writeHead(405).end();
    }
  } catch {
    if (!response.headersSent) response.writeHead(500);
    response.end();
  }
}).listen(Number(process.env.PORT || 80), "0.0.0.0");
