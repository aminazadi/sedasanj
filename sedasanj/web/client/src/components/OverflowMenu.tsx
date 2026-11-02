import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface MenuAction { label: string; onClick: () => void; disabled?: boolean }

/** "More" menu: keeps rarely used actions and technical details out of the card header. */
export default function OverflowMenu({ label, actions, details }: { label: string; actions: MenuAction[]; details?: Array<{ term: string; value: string; ltr?: boolean }> }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // Portalled and fixed so neighbouring stacking contexts (the title band, the message bubbles) cannot cover or clip it.
  useLayoutEffect(() => {
    if (!open) { setPosition(null); return; }
    const place = () => {
      const trigger = triggerRef.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;
      const anchor = trigger.getBoundingClientRect();
      const margin = 8;
      const left = Math.min(Math.max(anchor.left, margin), Math.max(window.innerWidth - menu.offsetWidth - margin, margin));
      setPosition({ top: anchor.bottom + 4, left });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); triggerRef.current?.focus(); } };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("pointerdown", onPointerDown); document.removeEventListener("keydown", onKeyDown); };
  }, [open]);
  return (
    <>
      <button ref={triggerRef} type="button" className={`flex h-9 w-9 items-center justify-center border border-[#898989] text-[#4B6E48] hover:bg-[#F2F0EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] ${open ? "bg-[#F2F0EF]" : "bg-white"}`} aria-haspopup="menu" aria-expanded={open} aria-label={label} title={label} onClick={() => setOpen((current) => !current)}>
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
      </button>
      {open ? createPortal(
        <div ref={menuRef} role="menu" dir="rtl" className="fixed z-50 w-64 max-w-[calc(100vw-1rem)] border border-[color:var(--line)] bg-[#F2F0EF] py-1 shadow-lg" style={{ top: position?.top ?? 0, left: position?.left ?? 0, visibility: position ? "visible" : "hidden" }}>
          {actions.map((action) => (
            <button key={action.label} type="button" role="menuitem" className="block w-full px-3 py-2 text-start text-sm text-slate-700 hover:bg-white hover:text-[#4B6E48] focus-visible:bg-white focus-visible:outline-none disabled:cursor-not-allowed disabled:text-[#898989] disabled:hover:bg-transparent" disabled={action.disabled} onClick={() => { setOpen(false); action.onClick(); }}>
              {action.label}
            </button>
          ))}
          {details?.length ? (
            <dl className="mt-1 space-y-1 border-t border-[color:var(--line)] px-3 py-2 text-[11px] text-slate-500">
              {details.map((item) => (
                <div key={item.term} className="flex justify-between gap-3"><dt>{item.term}</dt><dd className="min-w-0 truncate text-slate-700" dir={item.ltr ? "ltr" : undefined}>{item.value}</dd></div>
              ))}
            </dl>
          ) : null}
        </div>,
        document.body,
      ) : null}
    </>
  );
}
