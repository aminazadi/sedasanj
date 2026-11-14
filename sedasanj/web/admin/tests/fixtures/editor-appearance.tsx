import React from "react";
import tinymce from "tinymce";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import RichTextEditor from "../../src/components/RichTextEditor";
import RichDocumentEditor from "../../../client/src/components/RichDocumentEditor";
import MarkdownMessage from "../../../client/src/components/MarkdownMessage";
import { ReleaseNotes } from "../../../shared/components/ReleaseTimeline";
import "../../src/index.css";
import "../../../client/src/components/markdown-content.css";
import "../../../client/src/components/document-print.css";
import "../../../client/src/pages/Landing.css";
import "../../../client/src/pages/PublicPages.css";

const html = `<h2>عنوان آزمایشی</h2><h3>زیرعنوان</h3><h4>عنوان بخش</h4>
<p>متن <strong>برجسته</strong> و <em>تأکید</em> و <u>زیرخط</u> و <s>حذف</s>
و <code>inline_code</code> و <mark>علامت</mark> و <a href="https://example.com">پیوند</a></p>
<ul><li>فهرست</li></ul><ol><li>ترتیب</li></ol><blockquote>نقل قول</blockquote>
<pre class="language-bash"><code>echo "ready"</code></pre>
<table><thead><tr><th>عنوان</th></tr></thead><tbody><tr><td>محتوا</td></tr></tbody></table><hr>`;
const markdown = `# سند آزمایشی

## عنوان آزمایشی

### زیرعنوان

متن **برجسته** و *تأکید* و [پیوند](https://example.com)

- فهرست

1. ترتیب

> نقل قول

\`\`\`js
const ready = true;
\`\`\`

| عنوان |
| --- |
| محتوا |

---`;

function App() {
  return (
    <MemoryRouter>
      <main style={{ padding: 24, background: "#f2f0ef" }}>
        <section id="release">
          <RichTextEditor value={html} onChange={() => {}} />
          <ReleaseNotes html={html} sanitize={(value) => value} />
        </section>
        <section id="help">
          <RichTextEditor value={html} onChange={() => {}} onPickMedia={() => {}} />
          <div className="public-site marketing-site">
            <div className="prose-help" dangerouslySetInnerHTML={{ __html: html }} />
          </div>
        </section>
        <section id="document">
          <RichDocumentEditor content={markdown} expectedContent={markdown} path="/unused"
            onSaved={() => {}} onDraftChange={() => {}} />
          <div className="document-body"><MarkdownMessage content={markdown} /></div>
        </section>
        <pre id="results">waiting</pre>
      </main>
    </MemoryRouter>
  );
}
createRoot(document.getElementById("root")!).render(<App />);

const timer = setInterval(async () => {
  const frames = Array.from(document.querySelectorAll<HTMLIFrameElement>("iframe.tox-edit-area__iframe"));
  if (frames.length !== 3 || frames.some((frame) => !frame.contentDocument?.querySelector("h2"))) return;
  clearInterval(timer);
  await document.fonts.ready;
  await Promise.all(frames.map((frame) => frame.contentDocument!.fonts.ready));
  const properties = [
    "font-family", "font-size", "font-weight", "font-synthesis", "line-height", "color",
    "background-color", "margin-top", "margin-bottom", "padding-top", "padding-right",
    "padding-bottom", "padding-left", "border-top-width", "border-top-color", "text-align",
    "direction", "list-style-type",
  ];
  const failures: string[] = [];
  for (const frame of frames) {
    if (!frame.contentDocument!.fonts.check("14px Vazirmatn")) failures.push("Local body font unavailable");
  }
  if (!frames[1].contentDocument!.fonts.check('22px Vazirmatn')) {
    failures.push("Local heading font unavailable");
  }
  const helpHeading = frames[1].contentDocument!.querySelector("h2")!;
  const headingStyle = frames[1].contentWindow!.getComputedStyle(helpHeading);
  if (!headingStyle.fontFamily.startsWith("Vazirmatn") || headingStyle.fontSize !== "22px") {
    failures.push("Help heading must use normalized Vazirmatn typography");
  }
  for (const button of document.querySelectorAll(".tox-tbtn")) {
    if (getComputedStyle(button).color !== "rgb(75, 110, 72)") failures.push("Toolbar color mismatch");
  }
  const cases = [
    [0, "release", ".release-notes"],
    [1, "help", ".prose-help"],
    [2, "document", ".document-body .markdown-message"],
  ] as const;
  for (const [index, id, selector] of cases) {
    const frame = frames[index];
    const reader = document.querySelector(`#${id} ${selector}`)!;
    for (const tag of ["h1", "h2", "h3", "h4", "p", "strong", "em", "u", "s", "mark", "a",
      "ul", "ol", "li", "blockquote", "pre", "code", "table", "th", "td", "hr"]) {
      const edited = frame.contentDocument!.querySelector(tag);
      const published = reader.querySelector(tag);
      if (!published) continue;
      if (!edited) { failures.push(`${id} missing ${tag}`); continue; }
      const actual = frame.contentWindow!.getComputedStyle(edited);
      const expected = getComputedStyle(published);
      if (tag === "pre") {
        const textStyle = getComputedStyle(published.querySelector("code") ?? published);
        for (const token of edited.querySelectorAll("span, code")) {
          const tokenStyle = frame.contentWindow!.getComputedStyle(token);
          for (const property of ["font-family", "font-size", "font-weight", "line-height", "color"]) {
            if (tokenStyle.getPropertyValue(property) !== textStyle.getPropertyValue(property)) {
              failures.push(`${id} code token ${property}: ${tokenStyle.getPropertyValue(property)} != ${textStyle.getPropertyValue(property)}`);
            }
          }
        }
      }
      for (const property of properties) {
        const a = actual.getPropertyValue(property);
        const b = expected.getPropertyValue(property);
        if (a !== b) failures.push(`${id} ${tag} ${property}: ${a} != ${b}`);
      }
    }
  }
  const releaseEditor = tinymce.get(frames[0].id.replace(/_ifr$/, ""));
  if (!releaseEditor) failures.push("Release editor unavailable");
  else {
    releaseEditor.execCommand("mceLink");
    await new Promise((resolve) => setTimeout(resolve, 100));
    const dialog = document.querySelector<HTMLElement>(".tox-dialog");
    const save = dialog?.querySelector<HTMLElement>(".tox-button:not(.tox-button--secondary)");
    if (!save) failures.push("Link dialog unavailable");
    else {
      const style = getComputedStyle(save);
      if (style.backgroundColor !== "rgb(75, 110, 72)") failures.push("Dialog button color mismatch");
      if (!style.fontFamily.includes("Vazirmatn")) failures.push("Dialog font mismatch");
    }
    document.querySelector<HTMLButtonElement>(".tox-dialog__header .tox-button")?.click();
  }
  document.getElementById("results")!.textContent = JSON.stringify({ passed: failures.length === 0, viewportWidth: innerWidth, failures }, null, 2);
}, 200);
