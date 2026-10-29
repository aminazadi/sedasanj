import assert from "node:assert/strict";
import { readdir, stat } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const assetDirectories = [
  new URL("../src/assets/", import.meta.url),
  new URL("../../admin/src/assets/", import.meta.url),
];
const rasterSourcePattern = /\.(?:png|jpe?g)$/i;
const maximumWebpBytes = 400 * 1024;

test("panel raster assets use bounded WebP files", async () => {
  for (const directory of assetDirectories) {
    const entries = await readdir(directory, { withFileTypes: true });
    const rasterSources = entries.filter((entry) => entry.isFile() && rasterSourcePattern.test(entry.name));
    assert.deepEqual(rasterSources, [], `${fileURLToPath(directory)} contains unoptimized raster assets`);

    for (const entry of entries.filter((item) => item.isFile() && item.name.endsWith(".webp"))) {
      const asset = new URL(entry.name, directory);
      const details = await stat(asset);
      assert.ok(details.size <= maximumWebpBytes, `${fileURLToPath(asset)} exceeds the 400 KiB asset budget`);
    }
  }
});
