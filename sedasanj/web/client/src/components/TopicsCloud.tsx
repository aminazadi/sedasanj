import { useState, type CSSProperties, type ReactNode } from "react";
import { fmt } from "../api";

const tones = [
  "border-brand-200 bg-brand-50 text-brand-800",
  "border-emerald-200 bg-emerald-50 text-emerald-800",
  "border-sky-200 bg-sky-50 text-sky-800",
  "border-amber-200 bg-amber-50 text-amber-900",
];

const VISIBLE_TOPICS = 12;

export function TopicsCloud({ rows, emptyState }: { rows: Array<[string, number]>; emptyState: ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const counts = rows.map(([, count]) => count);
  const max = Math.max(1, ...counts);
  const min = Math.min(max, ...counts);
  return <section className="min-w-0 bg-[#F2F0EF] p-5"><h3 className="mb-4 text-sm font-bold text-slate-800">موضوعات پرتکرار</h3>{rows.length ? <><ul className="flex min-h-44 flex-wrap content-center items-center justify-center gap-3 py-3" aria-label="موضوعات پرتکرار">{(expanded ? rows : [...rows].sort((a, b) => b[1] - a[1]).slice(0, VISIBLE_TOPICS)).map(([label, count], index) => {
    const weight = max === min ? 0.5 : (count - min) / (max - min);
    const style = { fontSize: `${(0.75 + weight * 0.6).toFixed(2)}rem`, padding: `${(0.25 + weight * 0.2).toFixed(2)}rem ${(0.6 + weight * 0.3).toFixed(2)}rem` } as CSSProperties;
    return <li key={label} style={style} className={`inline-flex max-w-full items-center gap-2 rounded-full border font-bold leading-snug ${tones[index % tones.length]}`}><span className="min-w-0 break-words text-center">{label}</span><span className="inline-flex min-w-7 shrink-0 items-center justify-center rounded-full bg-white/80 px-1.5 py-0.5 text-xs font-bold tabular-nums" aria-label={`${fmt.int(count)} مورد`}>{fmt.int(count)}</span></li>;
  })}</ul>{rows.length > VISIBLE_TOPICS ? <div className="mt-2 text-center"><button type="button" className="text-sm font-medium text-[#4B6E48] underline decoration-dotted underline-offset-4" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "نمایش کمتر" : `نمایش بیشتر (${fmt.int(rows.length - VISIBLE_TOPICS)} موضوع دیگر)`}</button></div> : null}</> : emptyState}</section>;
}
