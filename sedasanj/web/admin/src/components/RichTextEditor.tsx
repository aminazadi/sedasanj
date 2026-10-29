// Self-hosted TinyMCE (GPL licence key); bundled by Vite so the admin panel never loads a CDN.
import "tinymce/tinymce";
import "tinymce/models/dom/model";
import "tinymce/themes/silver";
import "tinymce/icons/default";
import "tinymce/skins/ui/oxide/skin.js";
import "tinymce/skins/ui/oxide/content.js";
import "tinymce/skins/content/default/content.js";
import "tinymce/plugins/autolink";
import "tinymce/plugins/autoresize";
import "tinymce/plugins/code";
import "tinymce/plugins/codesample";
import "tinymce/plugins/directionality";
import "tinymce/plugins/fullscreen";
import "tinymce/plugins/link";
import "tinymce/plugins/lists";
import "tinymce/plugins/searchreplace";
import "tinymce/plugins/table";
import "tinymce/plugins/wordcount";
import "tinymce-i18n/langs7/fa.js";
import { Editor } from "@tinymce/tinymce-react";

export const CHANGELOG_TEMPLATE = `<h2>✨ امکانات جدید</h2><ul><li></li></ul>
<h2>🛠 بهبودها</h2><ul><li></li></ul>
<h2>🐞 رفع اشکال</h2><ul><li></li></ul>
<h2>🔒 امنیتی</h2><ul><li></li></ul>
<h2>⚠️ نکات ارتقا</h2><p></p>`;

/** Turns a YouTube/Aparat page URL into the embed URL the server allows, or null. */
export function toEmbedUrl(raw: string): string | null {
  try {
    const url = new URL(raw.trim());
    const host = url.hostname.replace(/^www\./, "");
    if (host === "youtube.com" || host === "youtu.be" || host === "youtube-nocookie.com") {
      const id = host === "youtu.be" ? url.pathname.slice(1) : url.searchParams.get("v") ?? url.pathname.split("/").pop();
      return id && /^[A-Za-z0-9_-]{6,20}$/.test(id) ? `https://www.youtube-nocookie.com/embed/${id}` : null;
    }
    if (host === "aparat.com") {
      const match = url.pathname.match(/\/v\/([A-Za-z0-9]{3,20})/) ?? url.pathname.match(/videohash\/([A-Za-z0-9]{3,20})/);
      return match ? `https://www.aparat.com/video/video/embed/videohash/${match[1]}/vt/frame` : null;
    }
  } catch {
    /* not a URL */
  }
  return null;
}

const RELEASE_ELEMENTS =
  "p,br,hr,h2,h3,h4,strong/b,em/i,u,s,mark,span,ul,ol,li,blockquote," +
  "code[class],pre[class],a[href|title|target|rel],table,thead,tbody,tr,th[colspan|rowspan],td[colspan|rowspan]";
// Help articles may also carry platform images/videos and the two allowed video embeds.
const HELP_ELEMENTS =
  RELEASE_ELEMENTS +
  ",figure,figcaption,img[src|alt|width|height],video[src|poster|controls|width|height|preload]," +
  "iframe[src|title|width|height|allowfullscreen|allow|loading|referrerpolicy|sandbox]";

export default function RichTextEditor({
  value,
  onChange,
  minHeight = 380,
  onPickMedia,
}: {
  value: string;
  onChange: (html: string) => void;
  minHeight?: number;
  /** Help-center mode: opens the media library; call `insert` with the chosen HTML. */
  onPickMedia?: (insert: (html: string) => void) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-300">
      <Editor
        licenseKey="gpl"
        value={value}
        onEditorChange={(html) => onChange(html)}
        init={{
          language: "fa",
          directionality: "rtl",
          skin_url: "default",
          content_css: "default",
          menubar: false,
          branding: false,
          promotion: false,
          statusbar: true,
          elementpath: false,
          min_height: minHeight,
          autoresize_bottom_margin: 24,
          plugins:
            "autolink autoresize code codesample directionality fullscreen link lists searchreplace table wordcount",
          toolbar:
            (onPickMedia ? "sjMedia sjEmbed | " : "sjTemplate | ") +
            "blocks | bold italic underline strikethrough | bullist numlist | " +
            "link blockquote codesample table | rtl ltr | removeformat searchreplace | code fullscreen",
          block_formats: "پاراگراف=p; تیتر ۱=h2; تیتر ۲=h3; تیتر ۳=h4; کد=pre",
          codesample_languages: [
            { text: "Bash", value: "bash" },
            { text: "PHP", value: "php" },
            { text: "JSON", value: "json" },
            { text: "INI", value: "ini" },
          ],
          link_default_target: "_blank",
          link_assume_external_targets: "https",
          // Mirror the server allowlist so authors see what readers will see.
          valid_elements: onPickMedia ? HELP_ELEMENTS : RELEASE_ELEMENTS,
          paste_data_images: false,
          content_style:
            "body{font-family:Vazirmatn,IRANSans,system-ui,sans-serif;font-size:14px;line-height:1.9}" +
            "pre{direction:ltr;text-align:left}",
          setup: (editor) => {
            if (onPickMedia) {
              editor.ui.registry.addButton("sjMedia", {
                text: "تصویر / ویدئو",
                tooltip: "درج تصویر یا ویدئوی آپلودشده",
                onAction: () => onPickMedia((html) => editor.insertContent(html)),
              });
              editor.ui.registry.addButton("sjEmbed", {
                text: "ویدئوی یوتیوب / آپارات",
                tooltip: "درج ویدئو از یوتیوب یا آپارات با لینک صفحه",
                onAction: () => {
                  const raw = window.prompt("لینک صفحهٔ ویدئو در یوتیوب یا آپارات:");
                  if (!raw) return;
                  const src = toEmbedUrl(raw);
                  if (!src) {
                    window.alert("فقط لینک یوتیوب یا آپارات پذیرفته می‌شود.");
                    return;
                  }
                  editor.insertContent(`<p><iframe src="${src}" title="ویدئو" width="640" height="360"></iframe></p>`);
                },
              });
            }
            editor.ui.registry.addButton("sjTemplate", {
              text: "درج قالب",
              tooltip: "اسکلت استاندارد تغییرات نسخه",
              onAction: () => {
                const empty = !editor.getContent({ format: "text" }).trim();
                if (empty || window.confirm("قالب استاندارد به انتهای متن اضافه شود؟")) {
                  editor.insertContent(CHANGELOG_TEMPLATE);
                }
              },
            });
          },
        }}
      />
    </div>
  );
}
