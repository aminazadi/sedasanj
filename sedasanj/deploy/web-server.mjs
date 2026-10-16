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

const server = http.createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname.startsWith("/v1/") || pathname === "/socket.io" || pathname.startsWith("/socket.io/")) {
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

server.listen(Number(process.env.PORT || 80), "0.0.0.0");
