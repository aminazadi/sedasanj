import assert from "node:assert/strict";
import test from "node:test";
import { unified } from "unified";
import remarkParse from "remark-parse";
import { appendExportLinks, exportDownloadPath, exportFiles } from "../src/components/assistantExportLinks.mjs";

const file = { export_id: "export-1", name: "calls.xlsx" };
const parse = (content) => unified().use(remarkParse).parse(content);

test("renders export links inside the message without file metadata", () => {
  const tree = parse("گزارش آماده است.");
  appendExportLinks(tree, [file]);
  assert.equal(tree.children.length, 2);
  assert.deepEqual(tree.children[1], {
    type: "paragraph",
    children: [{ type: "link", url: exportDownloadPath(file), children: [{ type: "text", value: "دریافت calls.xlsx" }] }],
  });
});

test("preserves existing inline and reference links without duplicate downloads", () => {
  for (const content of [
    `فایل [گزارش](${exportDownloadPath(file)}) آماده است.`,
    `[گزارش][download]\n\n[download]: ${exportDownloadPath(file)}`,
  ]) {
    const tree = parse(content);
    const before = structuredClone(tree);
    appendExportLinks(tree, [file]);
    assert.deepEqual(tree, before);
  }
});

test("code examples do not suppress real downloads and filenames stay literal", () => {
  const unsafe = { ...file, name: '[click](https://example.com) <script>.xlsx' };
  const tree = parse(`\`[file](${exportDownloadPath(file)})\``);
  appendExportLinks(tree, [unsafe, unsafe]);
  assert.equal(tree.children.length, 2);
  assert.equal(tree.children[1].children[0].children[0].value, `دریافت ${unsafe.name}`);
});

test("replayed tool runs preserve one download per export", () => {
  const second = { export_id: "export-2", name: "calls.pdf" };
  assert.deepEqual(exportFiles([{ files: [file] }, {}, { files: [file, second] }]), [file, second]);
  assert.equal(exportDownloadPath({ export_id: "a/b?x" }), "/v1/assistant/exports/a%2Fb%3Fx/download");
});
