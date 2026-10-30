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

test("static image inventory contains valid WebP dimensions and smaller responsive variants", async () => {
  assert.ok(manifest.length > 40, "inventory must cover both panels and public images");
  for (const asset of manifest) {
    const buffer = await readFile(new URL(asset.path, repository));
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

test("served image files use WebP across nested artwork and public assets", async () => {
  for (const relative of ["../src/assets/", "../../admin/src/assets/", "../public/"]) {
    for (const url of await files(new URL(relative, import.meta.url))) {
      // Vector geometry is source code for the animated logo, never an image URL.
      if (url.pathname.endsWith("/sedasanj-refined-master.svg")) continue;
      assert.ok(!/\.(?:png|jpe?g|gif|svg|avif)$/i.test(url.pathname), `${url.pathname} is not WebP`);
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
        await readFile(file);
        assert.ok(reference.endsWith(".webp") || reference.endsWith(".svg?raw"), `${url.pathname}: ${reference}`);
      }
    }
  }
});
