import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { selectPosition } from "../lib/selectPosition";

export interface SearchSelectOption {
  value: string;
  label: string;
  /** Extra text matched by the search box but not displayed (e.g. an email). */
  keywords?: string;
}

interface Props {
  options: SearchSelectOption[];
  value: string;
  onChange: (value: string) => void;
  /** Label of the "nothing selected" entry; it is hidden when empty. */
  emptyLabel?: string;
  searchPlaceholder?: string;
  ariaLabel: string;
  disabled?: boolean;
}

function normalize(text: string): string {
  return text.toLocaleLowerCase().replace(/ي/g, "ی").replace(/ك/g, "ک");
}

/** Dropdown with a search box; keyboard: arrows move, Enter selects, Escape closes. */
export default function SearchSelect({ options, value, onChange, emptyLabel = "بدون انتخاب", searchPlaceholder = "جستجو…", ariaLabel, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [position, setPosition] = useState<ReturnType<typeof selectPosition> | null>(null);
  const listId = useId();

  const visible = useMemo(() => {
    const needle = normalize(term.trim());
    const matches = needle
      ? options.filter((option) => normalize(`${option.label} ${option.keywords ?? ""}`).includes(needle))
      : options;
    return emptyLabel && !needle ? [{ value: "", label: emptyLabel }, ...matches] : matches;
  }, [options, term, emptyLabel]);

  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    searchRef.current?.focus();
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node) && !menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      if (triggerRef.current) {
        setPosition(selectPosition(triggerRef.current.getBoundingClientRect(), window.innerWidth, window.innerHeight));
      }
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);

  useEffect(() => setActive(0), [term, open]);

  function toggle() {
    setTerm("");
    setOpen((current) => !current);
  }

  function choose(next: string) {
    setOpen(false);
    triggerRef.current?.focus();
    if (next !== value) onChange(next);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      setOpen(false);
      triggerRef.current?.focus();
    }
    else if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(index + 1, visible.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = visible[active];
      if (option) choose(option.value);
    }
  }

  return (
    <div ref={rootRef} className="relative" onKeyDown={open ? onKeyDown : undefined}>
      <button
        ref={triggerRef}
        type="button"
        className="input flex items-center justify-between gap-2 text-start"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        disabled={disabled}
        onClick={toggle}
      >
        <span className={selected ? "truncate" : "truncate text-slate-500"}>{selected?.label ?? (emptyLabel || "—")}</span>
        <span aria-hidden="true" className="text-xs text-slate-400">▾</span>
      </button>
      {open ? createPortal(
        <div
          ref={menuRef}
          dir="rtl"
          className="fixed z-[10000] flex flex-col border border-[color:var(--line)] bg-[#F2F0EF] text-start shadow-lg"
          style={{ ...position, visibility: position ? "visible" : "hidden" }}
          onKeyDown={(event) => { event.stopPropagation(); onKeyDown(event); }}
        >
          <input
            ref={searchRef}
            className="input shrink-0 border-0 border-b border-[color:var(--line)] bg-[#F2F0EF]"
            type="search"
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            value={term}
            onChange={(event) => setTerm(event.target.value)}
          />
          <ul id={listId} role="listbox" aria-label={ariaLabel} className="min-h-0 overflow-y-auto text-sm">
            {visible.length === 0 ? (
              <li className="px-3 py-2 text-slate-500">موردی پیدا نشد؛ عبارت دیگری را جستجو کنید.</li>
            ) : (
              visible.map((option, index) => (
                <li
                  key={option.value || "__empty"}
                  role="option"
                  aria-selected={option.value === value}
                  className={`cursor-pointer px-3 py-2 ${index === active ? "bg-slate-100" : ""} ${option.value === value ? "font-bold" : ""}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => choose(option.value)}
                >
                  {option.label}
                </li>
              ))
            )}
          </ul>
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
