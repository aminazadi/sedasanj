import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const repository = new URL("../../../../", import.meta.url);
const manifest = JSON.parse(await readFile(new URL("../../image-assets.json", import.meta.url), "utf8"));

function webpDimensions(buffer) {
  assert.equal(buffer.toString("ascii", 0, 4), "RIFF");
  assert.equal(buffer.toString("ascii", 8, 12), "WEBP");
  const chunk = buffer.toString("ascii", 12, 16);
  if (chunk === "VP8X") return [buffer.readUIntLE(24, 3) + 1, buffer.readUIntLE(27, 3) + 1];
  if (chunk === "VP8 ") return [buffer.readUInt16LE(26) & 0x3fff, buffer.readUInt16LE(28) & 0x3fff];
  assert.equal(chunk, "VP8L");
  const bits = buffer.readUInt32LE(21);
  return [(bits & 0x3fff) + 1, ((bits >>> 14) & 0x3fff) + 1];
}

async function files(directory) {
  const result = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const url = new URL(entry.name + (entry.isDirectory() ? "/" : ""), directory);
    if (entry.isDirectory()) result.push(...await files(url));
    else result.push(url);
  }
  return result;
}

test("image inventory preserves animated SVGs and validates responsive WebP dimensions", async () => {
  assert.ok(manifest.length > 40, "inventory must cover both panels and public images");
  for (const asset of manifest) {
    const buffer = await readFile(new URL(asset.path, repository));
    if (asset.path.endsWith(".svg")) {
      const svg = buffer.toString("utf8");
      assert.match(svg, /@keyframes|<animate(?:Transform|Motion)?\b/);
      const viewBox = svg.match(/viewBox="([^"]+)"/)?.[1].split(/\s+/).map(Number);
      assert.deepEqual(viewBox?.slice(2), [asset.width, asset.height], asset.path);
      assert.equal(buffer.length, asset.bytes, asset.path);
      assert.deepEqual(asset.variants, [], "animated artwork must not have static alternatives");
      continue;
    }
    assert.deepEqual(webpDimensions(buffer), [asset.width, asset.height], asset.path);
    assert.equal(buffer.length, asset.bytes, asset.path);
    if (asset.path.includes("/src/assets/")) assert.ok(buffer.length <= 512 * 1024, `${asset.path} exceeds 512 KiB`);
    for (const variant of asset.variants) {
      const small = await readFile(new URL(variant.path, repository));
      const [width, height] = webpDimensions(small);
      assert.equal(width, variant.width, variant.path);
      assert.ok(Math.abs(height / width - asset.height / asset.width) <= 1 / width, variant.path);
      assert.equal(small.length, variant.bytes, variant.path);
      assert.ok(small.length < buffer.length, `${variant.path} must save transfer bytes`);
      assert.ok(small.length <= 250 * 1024, `${variant.path} exceeds 250 KiB`);
    }
  }
});

test("served images use WebP while preserving animated SVG assets", async () => {
  for (const relative of ["../src/assets/", "../../admin/src/assets/", "../public/"]) {
    for (const url of await files(new URL(relative, import.meta.url))) {
      // Vector geometry is source code for the animated logo, never an image URL.
      if (url.pathname.endsWith("/sedasanj-refined-master.svg")) continue;
      if (url.pathname.endsWith(".svg")) {
        assert.match(await readFile(url, "utf8"), /@keyframes|<animate(?:Transform|Motion)?\b/);
        continue;
      }
      assert.ok(!/\.(?:png|jpe?g|gif|avif)$/i.test(url.pathname), `${url.pathname} is not WebP`);
    }
  }
});

test("CSS and module artwork references resolve to existing files", async () => {
  for (const directory of ["../src/", "../../admin/src/"]) {
    for (const url of await files(new URL(directory, import.meta.url))) {
      if (!/\.(?:tsx?|css)$/.test(url.pathname)) continue;
      const source = await readFile(url, "utf8");
      const pattern = /["']((?:\.\.\/|\.\/)+assets\/[^"']+\.(?:webp|svg|png|jpe?g)(?:\?raw)?)["']/g;
      for (const [, reference] of source.matchAll(pattern)) {
        const file = new URL(reference.replace(/\?raw$/, ""), url);
        const buffer = await readFile(file);
        const animatedSvg = reference.endsWith(".svg") && /@keyframes|<animate(?:Transform|Motion)?\b/.test(buffer.toString("utf8"));
        assert.ok(reference.endsWith(".webp") || reference.endsWith(".svg?raw") || animatedSvg, `${url.pathname}: ${reference}`);
      }
    }
  }
});


test("operator awareness retains moving cards, scanning lens and rotating rings", async () => {
  const svg = await readFile(new URL("../src/assets/operator-awareness.svg", import.meta.url), "utf8");
  for (const name of ["scan", "scan-inner", "spin", ...Array.from({ length: 8 }, (_, index) => `move${index}`)]) {
    assert.ok(svg.includes(`@keyframes ${name} `), `missing animation ${name}`);
  }
  const landing = await readFile(new URL("../src/pages/Landing.tsx", import.meta.url), "utf8");
  assert.match(landing, /import awarenessArt from "[^"]+operator-awareness\.svg"/);
  const image = landing.match(/<img[^>]+src=\{awarenessArt\}[^>]*>/)?.[0];
  assert.ok(image, "landing must render the animated artwork");
  assert.ok(!image.includes("srcSet="), "static alternatives must never replace animated SVGs");
  assert.ok(!manifest.some((asset) => /operator-awareness.*\.webp$/.test(asset.path)));
});
