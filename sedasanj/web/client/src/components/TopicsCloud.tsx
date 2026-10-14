import type { ReactNode } from "react";
import { fmt } from "../api";

const tones = [
  "border-brand-200 bg-brand-50 text-brand-800",
  "border-emerald-200 bg-emerald-50 text-emerald-800",
  "border-sky-200 bg-sky-50 text-sky-800",
  "border-amber-200 bg-amber-50 text-amber-900",
];

export function TopicsCloud({ rows, emptyState }: { rows: Array<[string, number]>; emptyState: ReactNode }) {
  const max = Math.max(1, ...rows.map(([, count]) => count));
  return <section className="min-w-0 bg-[#F2F0EF] p-5"><h3 className="mb-4 text-sm font-bold text-slate-800">موضوعات پرتکرار</h3>{rows.length ? <ul className="flex min-h-44 flex-wrap content-center items-center justify-center gap-2.5 py-3" aria-label="موضوعات پرتکرار">{rows.map(([label, count], index) => {
    const size = count / max >= 0.75 ? "text-lg sm:text-xl" : count / max >= 0.4 ? "text-base sm:text-lg" : "text-sm sm:text-base";
    return <li key={label} className={`inline-flex max-w-full items-center gap-2 rounded-full border px-3 py-2 font-bold leading-snug ${tones[index % tones.length]} ${size}`}><span className="min-w-0 break-words text-center">{label}</span><span className="inline-flex min-w-7 shrink-0 items-center justify-center rounded-full bg-white/80 px-1.5 py-0.5 text-xs font-bold tabular-nums" aria-label={`${fmt.int(count)} مورد`}>{fmt.int(count)}</span></li>;
  })}</ul> : emptyState}</section>;
}
