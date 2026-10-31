import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { fmt } from "../../api";

const GOOD = "#4b6e48";
const BAD = "#8a4b3f";

/** Small trend line; time runs left to right like the full charts. Null points are skipped. */
export function Sparkline({ values, tone = "good" }: { values: Array<number | null>; tone?: "good" | "bad" }) {
  const points = values.map((value, index) => ({ value, index })).filter((item): item is { value: number; index: number } => item.value != null);
  if (points.length < 2) return <div className="exec-spark" aria-hidden="true" />;
  const width = 200;
  const height = 36;
  const min = Math.min(...points.map((item) => item.value));
  const max = Math.max(...points.map((item) => item.value));
  const x = (index: number) => (index * width) / Math.max(values.length - 1, 1);
  const y = (value: number) => height - 3 - ((value - min) / (max - min || 1)) * (height - 6);
  const line = points.map((item, index) => `${index ? "L" : "M"}${x(item.index).toFixed(1)} ${y(item.value).toFixed(1)}`).join(" ");
  const color = tone === "bad" ? BAD : GOOD;
  return <svg className="exec-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
    <path d={`${line} L${x(points[points.length - 1].index)} ${height} L${x(points[0].index)} ${height}Z`} fill={color} opacity="0.09" />
    <path d={line} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
  </svg>;
}

export type Polarity = "higher_better" | "lower_better" | "neutral";

/** Change badge. unit "percent" = relative change, "points" = percentage points, "score" = score points. */
export function DeltaBadge({ change, unit, polarity = "higher_better" }: { change: number | null; unit: "percent" | "points" | "score"; polarity?: Polarity }) {
  if (change == null) return <span className="exec-delta is-flat" title="دورهٔ قبل دادهٔ کافی ندارد">بدون مقایسه</span>;
  const flat = Math.abs(change) < (unit === "percent" ? 1 : 0.5);
  const good = polarity === "neutral" ? null : (change > 0) === (polarity === "higher_better");
  const tone = flat || good == null ? "is-flat" : good ? "is-good" : "is-bad";
  const suffix = unit === "percent" ? "٪" : unit === "points" ? " واحد" : " امتیاز";
  return <span className={`exec-delta ${tone}`} title="نسبت به دورهٔ قبل"><span aria-hidden="true">{flat ? "•" : change > 0 ? "▲" : "▼"}</span>{fmt.decimal(Math.abs(change))}{suffix}</span>;
}

export interface KpiTileProps {
  label: string;
  value: ReactNode;
  unit?: string;
  foot: ReactNode;
  delta: ReactNode;
  series?: Array<number | null>;
  seriesTone?: "good" | "bad";
  to?: string;
  footer?: ReactNode;
}

export function KpiTile({ label, value, unit, foot, delta, series, seriesTone, to, footer }: KpiTileProps) {
  const body = <>
    <span className="text-[13px] text-slate-500">{label}</span>
    <strong className="exec-kpi__value">{value}{unit ? <small>{unit}</small> : null}</strong>
    {series ? <Sparkline values={series} tone={seriesTone} /> : footer ?? <div className="exec-spark" aria-hidden="true" />}
    <div className="flex items-center justify-between gap-2 text-xs text-slate-500"><span className="min-w-0 truncate">{foot}</span>{delta}</div>
  </>;
  return to ? <Link to={to} className="card exec-kpi exec-kpi--link">{body}</Link> : <div className="card exec-kpi">{body}</div>;
}
