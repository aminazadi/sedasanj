import { createPortal } from "react-dom";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

export interface FilterBarField {
  /** Stable key; also used to remember which fields the user has added. */
  id: string;
  /** Shown in the "add filter" menu and above the control. */
  label: string;
  /** True while the field holds a value; active fields are always visible. */
  active: boolean;
  /** Resets the field's value. Called when the user removes the field. */
  onRemove: () => void;
  /** The input, select or picker. */
  control: ReactNode;
  /** Always visible and not removable (for fields without an "all" value). */
  pinned?: boolean;
  /** Leaves the field out entirely, e.g. for a role that cannot use it. */
  hidden?: boolean;
  /** Tailwind width classes for the field block. */
  className?: string;
}

interface FilterBarProps {
  fields: FilterBarField[];
  /** True when anything is filtered; controls whether the clear button shows. */
  hasActive: boolean;
  /** Resets every filter. */
  onClear: () => void;
  /** When set, the bar is a form with an apply button (for filters applied on submit). */
  onApply?: () => void;
  /** Extra buttons placed after the standard ones. */
  actions?: ReactNode;
}

function FunnelPlusIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 4h18l-7 8.5V19l-4 2v-8.5z" />
    </svg>
  );
}

function ClearFiltersIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v5M14 11v5" />
    </svg>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

/**
 * One multi-select for every filter of a table: tick the filters you need in "فیلترها" and their fields
 * appear; untick (or press ×) to remove one. A clear icon shows only while something is filtered.
 */
export function useFilterBar({ fields, hasActive, onClear, onApply, actions }: FilterBarProps): { toolbar: ReactNode; fields: ReactNode } {
  const available = fields.filter((field) => !field.hidden);
  const [added, setAdded] = useState<string[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLUListElement>(null);
  const [menuBox, setMenuBox] = useState<{ top: number; left: number; maxHeight: number; dir: "rtl" | "ltr" } | null>(null);

  // A filter that gets a value from elsewhere (URL, reset) must be visible.
  const activeKey = available.filter((field) => field.active).map((field) => field.id).join("|");
  useEffect(() => {
    const ids = activeKey ? activeKey.split("|") : [];
    setAdded((current) => (ids.every((id) => current.includes(id)) ? current : [...current, ...ids.filter((id) => !current.includes(id))]));
  }, [activeKey]);

  const isShown = useCallback((field: FilterBarField) => field.pinned || field.active || added.includes(field.id), [added]);
  const visible = [
    ...available.filter((field) => field.pinned),
    ...added.map((id) => available.find((field) => field.id === id)).filter((field): field is FilterBarField => Boolean(field && !field.pinned)),
    ...available.filter((field) => !field.pinned && !added.includes(field.id) && field.active),
  ];
  const selectable = available.filter((field) => !field.pinned);
  const selectedCount = selectable.filter(isShown).length;

  // The menu is portalled and fixed so no ancestor can clip it; it is placed under the button and kept
  // inside the page area (main, else the viewport), with its height capped to the space left.
  useLayoutEffect(() => {
    if (!menuOpen) {
      setMenuBox(null);
      return;
    }
    const place = () => {
      const trigger = triggerRef.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;
      const bounds = (trigger.closest("main") ?? document.documentElement).getBoundingClientRect();
      const margin = 8;
      const minLeft = Math.max(bounds.left, 0) + margin;
      const maxRight = Math.min(bounds.right, window.innerWidth) - margin;
      const anchor = trigger.getBoundingClientRect();
      const dir = getComputedStyle(trigger).direction === "rtl" ? "rtl" : "ltr";
      const width = Math.min(menu.offsetWidth, maxRight - minLeft);
      let left = anchor.left;
      left = Math.min(Math.max(left, minLeft), Math.max(maxRight - width, minLeft));
      const top = anchor.bottom + 4;
      const bottom = Math.min(bounds.bottom, window.innerHeight) - margin;
      setMenuBox({ top, left, maxHeight: Math.max(bottom - top, 120), dir });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [menuOpen]);

  function addField(id: string) {
    setAdded((current) => (current.includes(id) ? current : [...current, id]));
  }

  function removeField(field: FilterBarField) {
    setAdded((current) => current.filter((id) => id !== field.id));
    field.onRemove();
  }

  function clearAll() {
    setAdded([]);
    onClear();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    onApply?.();
  }

  const Wrapper = onApply ? "form" : "div";

  const toolbar = (
    <>
      {selectable.length > 0 ? (
        <div className="relative" ref={rootRef}>
          <button
            ref={triggerRef}
            type="button"
            className="btn-ghost inline-flex min-h-[42px] items-center gap-2 px-3 py-2 text-sm"
            aria-haspopup="true"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <FunnelPlusIcon />
            <span>فیلترها</span>
            {selectedCount > 0 ? <span className="inline-flex h-5 min-w-[1.25rem] items-center justify-center bg-[#4B6E48] px-1 text-xs text-[#F2F0EF]">{selectedCount.toLocaleString("fa-IR")}</span> : null}
            <ChevronIcon open={menuOpen} />
          </button>
          {menuOpen ? createPortal(
            <ul
              ref={menuRef}
              role="group"
              aria-label="انتخاب فیلترها"
              className="fixed z-50 min-w-[13rem] overflow-y-auto border border-[color:var(--line)] bg-[#F2F0EF] py-1 shadow-lg"
              dir={menuBox?.dir ?? "rtl"}
              style={{ top: menuBox?.top ?? 0, left: menuBox?.left ?? 0, maxHeight: menuBox?.maxHeight, width: "max-content", visibility: menuBox ? "visible" : "hidden" }}
            >
              {selectable.map((field) => {
                const checked = isShown(field);
                return (
                  <li key={field.id} role="none">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={checked}
                      className="flex w-full items-center justify-between gap-4 px-3 py-2 text-start text-sm text-slate-700 hover:bg-white focus-visible:bg-white focus-visible:outline-none"
                      onClick={() => (checked ? removeField(field) : addField(field.id))}
                    >
                      <span>{field.label}</span>
                      <span dir="ltr" aria-hidden="true" className={`relative inline-block h-5 w-9 shrink-0 transition-colors ${checked ? "bg-[#4B6E48]" : "bg-[#B2AC88]"}`}>
                        <span className="absolute top-0.5 h-4 w-4 bg-white shadow-sm transition-all" style={{ left: checked ? "1.125rem" : "0.125rem" }} />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          , document.body) : null}
        </div>
      ) : null}
      {actions}
    </>
  );

  const fieldsRow =
    visible.length === 0 ? null : (
      <Wrapper className="flex flex-wrap items-end gap-3" {...(onApply ? { onSubmit: submit } : {})}>
      {visible.map((field) => (
        <div key={field.id} className={`min-w-[10rem] flex-1 sm:flex-none ${field.className ?? "sm:w-48"}`}>
          <div className="mb-1 flex items-center justify-between gap-2">
            <label className="label !mb-0 text-xs">{field.label}</label>
            {field.pinned ? null : (
              <button type="button" className="inline-flex h-6 w-6 items-center justify-center text-[#898989] transition hover:text-red-600" onClick={() => removeField(field)} aria-label={`حذف فیلتر ${field.label}`} title="حذف فیلتر">
                <TrashIcon />
              </button>
            )}
          </div>
          {field.control}
        </div>
      ))}

        {onApply ? <button type="submit" className="btn min-h-[42px] px-4">اعمال فیلتر</button> : null}
        {hasActive ? (
          <button type="button" className="inline-flex h-[42px] w-[42px] items-center justify-center border !border-red-600 bg-red-50 text-red-600 transition hover:!bg-red-600 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-600" onClick={clearAll} aria-label="پاک کردن فیلترها" title="پاک کردن فیلترها">
            <ClearFiltersIcon />
          </button>
        ) : null}
      </Wrapper>
    );

  return { toolbar, fields: fieldsRow };
}

/** A self-contained bar: the filters button and clear button, with the chosen fields in a row below. */
export default function FilterBar({ className = "", ...props }: FilterBarProps & { className?: string }) {
  const { toolbar, fields } = useFilterBar(props);
  return (
    <div className={`filter-bar space-y-3 ${className}`}>
      <div className="flex flex-wrap items-end gap-3">{toolbar}</div>
      {fields}
    </div>
  );
}

export interface FilterSelectOption {
  value: string;
  label: string;
}

/** Select for a FilterBar field; the empty value is labelled "همه" unless allLabel is null. */
export function FilterSelect({ value, onChange, options, allLabel = "همه", ariaLabel }: { value: string; onChange: (value: string) => void; options: FilterSelectOption[]; allLabel?: string | null; ariaLabel?: string }) {
  return (
    <select className="input" value={value} aria-label={ariaLabel} onChange={(event) => onChange(event.target.value)}>
      {allLabel === null ? null : <option value="">{allLabel}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
