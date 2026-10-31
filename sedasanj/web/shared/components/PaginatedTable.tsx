import { Children, cloneElement, isValidElement, type ReactNode, type TableHTMLAttributes } from "react";
import { PageSizeSelect } from "./PageSizeSelect";

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
    <nav className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4" aria-label="صفحه‌بندی">
      <PageSizeSelect value={size} onChange={onSize} />
      <span className="text-xs text-slate-500">صفحه {(Math.floor(start / size) + 1).toLocaleString("fa-IR")} · {total.toLocaleString("fa-IR")} مورد</span>
      <div className="flex gap-2">
        <button className="btn-ghost text-sm" type="button" disabled={start === 0} onClick={() => onOffset(Math.max(0, start - size))}>صفحه قبل</button>
        <button className="btn-ghost text-sm" type="button" disabled={start + size >= total} onClick={() => onOffset(start + size)}>صفحه بعد</button>
      </div>
    </nav>
  </>;
}
