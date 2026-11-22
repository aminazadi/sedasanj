import { PagerArrow, PageSizeSelect } from "./PageSizeSelect";
import { Children, cloneElement, isValidElement, type ReactNode, type TableHTMLAttributes } from "react";

export function PaginatedTable({ children, size, offset, onOffset, onSize, ...props }: TableHTMLAttributes<HTMLTableElement> & {
  size: number; offset: number; onOffset: (offset: number) => void; onSize: (size: number) => void;
}) {
  let total = 0;
  const content = Children.map(children, (child) => {
    if (!isValidElement<{ children: ReactNode }>(child) || child.type !== "tbody") return child;
    const rows = Children.toArray(child.props.children);
    total = rows.length;
    const start = Math.min(offset, Math.max(0, Math.ceil(total / size) - 1) * size);
    return cloneElement(child, {}, rows.slice(start, start + size));
  });
  const start = Math.min(offset, Math.max(0, Math.ceil(total / size) - 1) * size);
  return <>
    <table {...props}>{content}</table>
    <nav className="mt-3 flex flex-wrap items-center justify-between gap-3" aria-label="صفحه‌بندی">
      <PageSizeSelect value={size} onChange={onSize} />
      <span className="text-xs text-slate-500">صفحه {(Math.floor(start / size) + 1).toLocaleString("fa-IR")} · {total.toLocaleString("fa-IR")} مورد</span>
      <div className="flex gap-2">
        <button className="inline-flex h-7 w-7 items-center justify-center opacity-60 transition hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-30" type="button" disabled={start === 0} onClick={() => onOffset(Math.max(0, start - size))} aria-label="صفحه قبل" title="صفحه قبل"><PagerArrow direction="prev" /></button>
        <button className="inline-flex h-7 w-7 items-center justify-center opacity-60 transition hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-30" type="button" disabled={start + size >= total} onClick={() => onOffset(start + size)} aria-label="صفحه بعد" title="صفحه بعد"><PagerArrow direction="next" /></button>
      </div>
    </nav>
  </>;
}
