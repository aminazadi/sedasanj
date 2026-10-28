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

export default function RichTextEditor({
  value,
  onChange,
  minHeight = 380,
}: {
  value: string;
  onChange: (html: string) => void;
  minHeight?: number;
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
            "sjTemplate | blocks | bold italic underline strikethrough | bullist numlist | " +
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
          valid_elements:
            "p,br,hr,h2,h3,h4,strong/b,em/i,u,s,mark,span,ul,ol,li,blockquote," +
            "code[class],pre[class],a[href|title|target|rel],table,thead,tbody,tr,th[colspan|rowspan],td[colspan|rowspan]",
          paste_data_images: false,
          content_style:
            "body{font-family:Vazirmatn,IRANSans,system-ui,sans-serif;font-size:14px;line-height:1.9}" +
            "pre{direction:ltr;text-align:left}",
          setup: (editor) => {
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
