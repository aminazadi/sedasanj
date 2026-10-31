import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../../shared/lib/siteFooter.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022 },
}).outputText;
const { defaultFooter, isSafeFooterUrl } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("footer permits internal paths, anchors, query strings and web URLs", () => {
  for (const url of ["/about", "/#features", "/help?q=test", "https://example.com/path", "http://example.com"]) {
    assert.equal(isSafeFooterUrl(url), true, url);
  }
  for (const link of [...defaultFooter.links, ...defaultFooter.legal_links]) {
    assert.equal(isSafeFooterUrl(link.url), true, link.url);
  }
});

test("footer rejects script, data, protocol-relative, credential and malformed destinations", () => {
  for (const url of ["javascript:alert(1)", "data:text/html,test", "//evil.example", "/\\evil.example", "/\nevil.example", "https://user:pass@example.com", "https://example.com/a b", "https:example.com", "about", ""]) {
    assert.equal(isSafeFooterUrl(url), false, url);
  }
});
