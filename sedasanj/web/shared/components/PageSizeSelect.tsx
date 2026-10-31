import { PAGE_SIZES } from "../lib/tablePagination.mjs";

export function PageSizeSelect({ value, onChange }: { value: number; onChange: (size: number) => void }) {
  return <label className="flex items-center gap-2 text-xs text-slate-500">
    تعداد نمایش
    <select className="input !w-auto min-w-20 !rounded-none text-sm" value={value} onChange={(event) => onChange(Number(event.target.value))}>
      {PAGE_SIZES.map((size) => <option key={size} value={size}>{size.toLocaleString("fa-IR")}</option>)}
    </select>
  </label>;
}
