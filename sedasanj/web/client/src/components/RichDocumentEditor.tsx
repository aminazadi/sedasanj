import { useEffect, useMemo, useRef, useState } from "react";
import { useBeforeUnload } from "react-router-dom";
import { Editor } from "@tinymce/tinymce-react";
import type { Editor as TinyEditor } from "tinymce";
import "tinymce/tinymce";
import "tinymce/models/dom/model";
import "tinymce/themes/silver";
import "tinymce/icons/default";
import "tinymce/skins/ui/oxide/skin.js";
import "tinymce/skins/ui/oxide/content.js";
import "tinymce/skins/content/default/content.js";
import "tinymce/plugins/autoresize";
import "tinymce/plugins/lists";
import "tinymce/plugins/link";
import "tinymce/plugins/table";
import "tinymce/plugins/searchreplace";
import "tinymce/plugins/wordcount";
import "tinymce/plugins/directionality";
import "tinymce-i18n/langs7/fa.js";
import { documentToHtml, documentToMarkdown } from "../lib/documentMarkdown.mjs";
import fontUrl from "../fonts/Vazirmatn-Variable.woff2?url";
import { request } from "../api";
import { ErrorBox } from "./Widgets";

export default function DocumentEditor({ content, expectedContent, path, onSaved, onDraftChange }: {
  content: string;
  expectedContent: string;
  path: string;
  onSaved: (content: string) => void;
  onDraftChange: (content: string | null) => void;
}) {
  const initial = useMemo(() => documentToHtml(content), [content]);
  const initialMount = useRef(initial);
  const [html, setHtml] = useState(initial);
  const baseline = useRef(initial);
  const expected = useRef(expectedContent);
  const editorRef = useRef<TinyEditor | null>(null);
  const syncing = useRef(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!dirty) return;
    const guard = (event: MouseEvent) => {
      const link = (event.target as Element).closest?.("a[href]");
      if (link && !window.confirm("تغییرات ذخیره نشده‌اند؛ بدون ذخیره خارج می‌شوید؟")) {
        event.preventDefault(); event.stopPropagation();
      }
    };
    document.addEventListener("click", guard, true);
    return () => document.removeEventListener("click", guard, true);
  }, [dirty]);
  useBeforeUnload((event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
  useEffect(() => {
    if (dirty) return;
    expected.current = expectedContent;
    const editor = editorRef.current;
    if (editor) {
      syncing.current = true;
      editor.setContent(initial);
      baseline.current = editor.getContent();
      setHtml(baseline.current);
      syncing.current = false;
    }
  }, [initial, expectedContent]);

  async function save() {
    const next = documentToMarkdown(html);
    if (!next.trim()) { setError("متن سند خالی است؛ پیش از ذخیره، متن را وارد کنید."); return; }
    setBusy(true); setError(null);
    try {
      await request(path, { method: "PATCH", body: { content: next, expected_content: expected.current } });
      baseline.current = html;
      expected.current = next;
      setDirty(false);
      onSaved(next);
      onDraftChange(null);
    } catch (err) {
      setError(`${(err as Error).message} متن شما در ویرایشگر باقی مانده است؛ دوباره تلاش کنید.`);
    } finally { setBusy(false); }
  }

  return <div className="document-editor pb-20">
    <Editor initialValue={initialMount.current} disabled={busy} licenseKey="gpl"
      onInit={(_, editor) => { editorRef.current = editor; baseline.current = editor.getContent(); setHtml(baseline.current); }}
      onEditorChange={(value) => {
        if (syncing.current) return;
        setHtml(value);
        const changed = value !== baseline.current;
        setDirty(changed);
        onDraftChange(changed ? documentToMarkdown(value) : null);
      }}
      init={{
        language: "fa", directionality: "rtl", skin_url: "default", content_css: "default",
        menubar: false, branding: false, promotion: false, elementpath: false,
        min_height: 520, autoresize_bottom_margin: 32,
        plugins: "autoresize lists link table searchreplace wordcount directionality",
        toolbar: "undo redo | blocks | bold italic strikethrough | bullist numlist | blockquote link table | rtl ltr | removeformat searchreplace",
        block_formats: "پاراگراف=p; عنوان=h1; تیتر=h2; زیرعنوان=h3",
        valid_elements: "p,br,hr,h1,h2,h3,h4,strong/b,em/i,s,ul,ol[start],li,blockquote,pre,code[class],a[href|title],table,thead,tbody,tr,th,td",
        paste_data_images: false,
        content_style: `@font-face{font-family:Vazirmatn;src:url('${fontUrl}') format('woff2');font-weight:100 900}body{font-family:Vazirmatn,sans-serif;font-size:14px;font-weight:350;line-height:2;color:#263226;margin:24px}h1,h2,h3,h4{color:#4b6e48;line-height:1.7;font-weight:500}h1{font-size:24px}h2{font-size:20px}h3{font-size:16px}table{border-collapse:collapse;width:100%}th{background:#f2f0ef}ul,ol{list-style-position:inside}td,th{border:1px solid #b2ac88;padding:8px}blockquote{border-right:3px solid #b2ac88;margin-right:0;padding-right:16px}pre{direction:ltr;text-align:left}a{color:#4b6e48}*{border-radius:0!important}`,
      }} />
    <ErrorBox message={error} />
    {dirty ? <div className="document-save-bar" role="region" aria-label="تغییرات ذخیره‌نشده">
      <span className="text-xs">تغییرات ذخیره نشده‌اند</span>
      <button type="button" className="btn whitespace-nowrap" disabled={busy} onClick={() => void save()}>{busy ? "در حال ذخیره…" : "ذخیره تغییرات"}</button>
    </div> : null}
  </div>;
}
