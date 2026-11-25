import { useEffect, useState } from "react";
import { Icon } from "@iconify/react";
import sparklesIcon from "@iconify-icons/lucide/sparkles";
import notebookPenIcon from "@iconify-icons/lucide/notebook-pen";
import graduationCapIcon from "@iconify-icons/lucide/graduation-cap";
import usersIcon from "@iconify-icons/lucide/users";
import messageSquareIcon from "@iconify-icons/lucide/message-square";
import micIcon from "@iconify-icons/lucide/mic";
import listChecksIcon from "@iconify-icons/lucide/list-checks";
import fileTextIcon from "@iconify-icons/lucide/file-text";
import bookOpenIcon from "@iconify-icons/lucide/book-open";
import lightbulbIcon from "@iconify-icons/lucide/lightbulb";
import layersIcon from "@iconify-icons/lucide/layers";
import clipboardListIcon from "@iconify-icons/lucide/clipboard-list";
import scrollTextIcon from "@iconify-icons/lucide/scroll-text";
import brainIcon from "@iconify-icons/lucide/brain";
import presentationIcon from "@iconify-icons/lucide/presentation";
import heartHandshakeIcon from "@iconify-icons/lucide/heart-handshake";

// Must match MENU_ICONS in the API (services/jalase_output_types.py) and CATEGORY_ICONS in the client Layout.
const ICONS: Array<{ name: string; label: string; icon: typeof sparklesIcon }> = [
  { name: "sparkles", label: "درخشش (پردازش هوشمند)", icon: sparklesIcon },
  { name: "notebook-pen", label: "دفترچه", icon: notebookPenIcon },
  { name: "graduation-cap", label: "کلاه فارغ‌التحصیلی", icon: graduationCapIcon },
  { name: "users", label: "گروه افراد", icon: usersIcon },
  { name: "message-square", label: "پیام", icon: messageSquareIcon },
  { name: "mic", label: "میکروفن", icon: micIcon },
  { name: "list-checks", label: "فهرست کارها", icon: listChecksIcon },
  { name: "file-text", label: "سند", icon: fileTextIcon },
  { name: "book-open", label: "کتاب", icon: bookOpenIcon },
  { name: "lightbulb", label: "ایده", icon: lightbulbIcon },
  { name: "layers", label: "لایه‌ها", icon: layersIcon },
  { name: "clipboard-list", label: "کلیپ‌بورد", icon: clipboardListIcon },
  { name: "scroll-text", label: "طومار", icon: scrollTextIcon },
  { name: "brain", label: "مغز", icon: brainIcon },
  { name: "presentation", label: "ارائه", icon: presentationIcon },
  { name: "heart-handshake", label: "همدلی", icon: heartHandshakeIcon },
];

/** A button showing the chosen menu icon; it opens a dialog with the whole icon library to pick from. */
export default function MenuIconPicker({ value, onChange }: { value: string; onChange: (name: string) => void }) {
  const [open, setOpen] = useState(false);
  const current = ICONS.find((item) => item.name === value) ?? ICONS[0];

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <button type="button" className="btn-ghost inline-flex h-10 items-center gap-2 px-3 py-0" onClick={() => setOpen(true)}>
        <Icon icon={current.icon} width={20} height={20} aria-hidden="true" />
        <span>{current.label}</span>
      </button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-950/55 p-4"
          onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="menu-icon-title" className="my-auto w-full max-w-lg border border-slate-200 bg-canvas p-6 shadow-xl">
            <h2 id="menu-icon-title" className="mb-1 text-xl font-bold">انتخاب آیکن منو</h2>
            <p className="mb-4 text-sm text-slate-600">آیکنی که کنار این دسته در منوی کناری پنل سازمان‌ها نشان داده می‌شود.</p>
            <div className="grid grid-cols-4 gap-2" role="radiogroup" aria-label="آیکن‌ها">
              {ICONS.map((item) => (
                <button key={item.name} type="button" role="radio" aria-checked={item.name === current.name} title={item.label}
                  className={`flex h-20 flex-col items-center justify-center gap-1 border text-xs ${item.name === current.name ? "border-brand-500 bg-brand-50 font-bold" : "border-slate-300 hover:bg-slate-100"}`}
                  onClick={() => { onChange(item.name); setOpen(false); }}>
                  <Icon icon={item.icon} width={26} height={26} aria-hidden="true" />
                  <span className="px-1 text-center leading-tight">{item.label}</span>
                </button>
              ))}
            </div>
            <div className="mt-4 flex justify-end"><button type="button" className="btn-ghost" onClick={() => setOpen(false)}>بستن</button></div>
          </section>
        </div>
      ) : null}
    </>
  );
}
