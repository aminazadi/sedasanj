import assert from "node:assert/strict";
import test from "node:test";
import { documentToHtml, documentToMarkdown } from "../src/lib/documentMarkdown.mjs";

test("rich text round trips Persian headings, emphasis, lists, links, tables, and code", () => {
  const source = "## تصمیم‌ها\n\n**تصویب شد** و *پیگیری* و ~~حذف~~\n\n- اقدام اول\n- اقدام دوم\n\n1. بررسی\n2. اجرا\n\n[تماس](/calls/fixture)\n\n| مسئول | اقدام |\n| --- | --- |\n| تیم محصول | انتشار |\n\n```js\nconst ready = true;\n```";
  const html = documentToHtml(documentToMarkdown(documentToHtml(source)));
  for (const pattern of [/<h2>تصمیم‌ها<\/h2>/, /<strong>تصویب شد<\/strong>/, /<em>پیگیری<\/em>/, /<s>حذف<\/s>/, /<ul>/, /<ol>/, /href="\/calls\/fixture"/, /<table>/, /<td>تیم محصول<\/td>/, /const ready = true/]) assert.match(html, pattern);
});

test("document rendering never activates model or editor supplied HTML and unsafe links", () => {
  const html = documentToHtml('<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[unsafe](javascript:alert(1))');
  assert.doesNotMatch(html, /<script|<img|href="javascript:/);
  assert.match(html, /&lt;script&gt;/);
});

test("edited table cells and task lists survive saving", () => {
  const html = documentToHtml(documentToMarkdown('<h2>اقدام‌ها</h2><table><thead><tr><th>مسئول</th><th>مهلت</th></tr></thead><tbody><tr><td>امین</td><td>فردا</td></tr></tbody></table><ul><li>پیگیری گزارش</li></ul>'));
  assert.match(html, /<td>امین<\/td>/);
  assert.match(html, /<td>فردا<\/td>/);
  assert.match(html, /<li>پیگیری گزارش<\/li>/);
});
