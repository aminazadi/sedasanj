import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PAGE_SIZES } from "../lib/tablePagination.mjs";

const useMenuLayoutEffect = typeof document === "undefined" ? useEffect : useLayoutEffect;

export function PageSizeSelect({ value, onChange }: { value: number; onChange: (size: number) => void }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number; width: number; maxHeight: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const listId = useId();

  useMenuLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      if (!trigger.current) return;
      const rect = trigger.current.getBoundingClientRect();
      const gap = 8;
      const width = Math.min(Math.max(rect.width, 140), window.innerWidth - gap * 2);
      const below = window.innerHeight - rect.bottom - gap * 2;
      const above = rect.top - gap * 2;
      const upward = below < 188 && above > below;
      const maxHeight = Math.max(0, Math.min(188, upward ? above : below));
      setPosition({
        top: upward ? rect.top - gap - maxHeight : rect.bottom + gap,
        left: Math.max(gap, Math.min(rect.right - width, window.innerWidth - width - gap)),
        width,
        maxHeight,
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]')?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!trigger.current?.contains(event.target as Node) && !menu.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open, position !== null]);

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  return <>
    <button
      ref={trigger}
      type="button"
      className="btn-ghost inline-flex items-center gap-3 !rounded-none text-xs"
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-controls={open ? listId : undefined}
      onClick={() => setOpen((current) => !current)}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          setOpen(true);
        } else if (event.key === "Escape") close();
      }}
    >
      <span>تعداد نمایش</span>
      <span>{value.toLocaleString("fa-IR")}</span>
      <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true"><path d={open ? "m5 12 5-5 5 5" : "m5 8 5 5 5-5"} /></svg>
    </button>
    {open && createPortal(
      <div
        ref={menu}
        id={listId}
        role="listbox"
        aria-label="تعداد نمایش"
        dir="rtl"
        className="overflow-y-auto border border-[#B2AC88] bg-[#F2F0EF] p-1 text-sm text-slate-700 shadow-lg"
        style={{ position: "fixed", zIndex: 10000, ...position, visibility: position ? "visible" : "hidden" }}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            close();
          } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            const options = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? []);
            const current = options.indexOf(document.activeElement as HTMLButtonElement);
            const next = event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : (current + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
            options[next]?.focus();
          } else if (event.key === "Tab") setOpen(false);
        }}
      >
        {PAGE_SIZES.map((size) => <button
          key={size}
          type="button"
          role="option"
          aria-selected={size === value}
          className={`block h-9 w-full px-3 text-right outline-none hover:bg-white focus:bg-white ${size === value ? "font-medium text-[#4B6E48]" : ""}`}
          onClick={() => { close(); if (size !== value) onChange(size); }}
        >{size.toLocaleString("fa-IR")}</button>)}
      </div>,
      trigger.current?.closest("dialog") ?? document.body,
    )}
  </>;
}
