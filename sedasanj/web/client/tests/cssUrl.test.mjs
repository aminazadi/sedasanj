import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";
import { build } from "vite";

const source = await readFile(new URL("../../shared/lib/cssUrl.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022 },
}).outputText;
const { cssUrl } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("production SVG data URLs remain quoted in CSS backgrounds", async () => {
  const result = await build({
    configFile: false,
    logLevel: "silent",
    plugins: [{
      name: "dialog-art-fixture",
      resolveId(id) { if (id.endsWith("dialog-art-fixture")) return id; },
      load(id) {
        if (id.endsWith("dialog-art-fixture")) return `export { default } from ${JSON.stringify(new URL("../src/assets/add-user.svg", import.meta.url).pathname)}`;
      },
    }],
    build: {
      write: false,
      lib: {
        entry: "dialog-art-fixture",
        formats: ["es"],
        fileName: "art",
      },
    },
  });
  const chunk = (Array.isArray(result) ? result[0] : result).output.find((item) => item.type === "chunk");
  const { default: asset } = await import(`data:text/javascript;base64,${Buffer.from(chunk.code).toString("base64")}`);
  assert.ok(asset.startsWith("data:image/svg+xml,"));
  assert.ok(asset.includes("'"), "Vite SVG attributes reproduce the production CSS delimiter issue");
  const background = cssUrl(asset);
  assert.ok(background.startsWith('url("'));
  assert.equal(JSON.parse(background.slice(4, -1)), asset);
});

test("file URLs with spaces and parentheses are quoted", () => {
  assert.equal(cssUrl("/assets/art (1).webp"), 'url("/assets/art (1).webp")');
});
