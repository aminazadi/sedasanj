import { Link } from "react-router-dom";
import { fmt, query, SENTIMENT_LABELS } from "../../api";
import type { KpiDashboard } from "../../types";
import { SENTIMENT_EMOJI } from "../Widgets";
import { DashboardCard } from "./DashboardCard";

const ORDER = ["happy", "satisfied", "neutral", "sad", "angry"] as const;
const COLORS: Record<string, string> = { happy: "#4b6e48", satisfied: "#7f9a7a", neutral: "#b2ac88", sad: "#a78a6c", angry: "#8a4b3f" };

function Chips({ rows, empty }: { rows: Array<[string, number]>; empty: string }) {
  return rows.length ? <div className="flex flex-wrap gap-1.5">{rows.map(([label, count]) => <span key={label} className="exec-chip">{label}<b>{fmt.int(count)}</b></span>)}</div> : <p className="text-xs text-slate-500">{empty}</p>;
}

/** Sentiment mix of analysed calls plus what customers object to and talk about most. */
export function VoiceOfCustomer({ sentiments, objections, topics, range }: { sentiments: KpiDashboard["sentiments"]; objections: Array<[string, number]>; topics: Array<[string, number]>; range: { from: string; to: string } }) {
  const counts = new Map(sentiments.map((item) => [item.key, item.count]));
  const total = ORDER.reduce((sum, key) => sum + (counts.get(key) ?? 0), 0);
  return <DashboardCard title="صدای مشتری" hint={total ? `احساس مشتری در ${fmt.int(total)} تماس تحلیل‌شده` : "احساس مشتری در تماس‌های تحلیل‌شده"} action={<Link to={`/calls${query({ from: range.from, to: range.to })}`} className="exec-link">تماس‌ها</Link>}>
    {total ? <>
      <div className="exec-strip" role="img" aria-label="سهم هر احساس">{ORDER.map((key) => (counts.get(key) ?? 0) ? <i key={key} style={{ width: `${((counts.get(key) ?? 0) * 100) / total}%`, background: COLORS[key] }} title={SENTIMENT_LABELS[key]} /> : null)}</div>
      <div className="grid grid-cols-5 gap-1 text-center">{ORDER.map((key) => {
        const count = counts.get(key) ?? 0;
        return <Link key={key} to={`/calls${query({ from: range.from, to: range.to, sentiment: key })}`} className="flex min-w-0 flex-col items-center gap-0.5 py-1 hover:bg-white/60">
          <span className="text-2xl leading-none" aria-hidden="true">{SENTIMENT_EMOJI[key]}</span>
          <strong className="mt-1 text-base font-bold tabular-nums" style={{ color: COLORS[key] }}>{fmt.int((count * 100) / total)}٪</strong>
          <span className="truncate text-[11px] text-slate-500">{SENTIMENT_LABELS[key]} · {fmt.int(count)}</span>
        </Link>;
      })}</div>
    </> : <p className="border border-dashed border-[color:var(--line-strong)] p-4 text-center text-xs text-slate-500">پس از تحلیل تماس‌ها، احساس مشتری اینجا نمایش داده می‌شود.</p>}
    <h3 className="mb-2 mt-5 text-[13px] font-bold text-slate-700">اعتراض‌های پرتکرار</h3>
    <Chips rows={objections.slice(0, 6)} empty="اعتراضی ثبت نشده است." />
    <h3 className="mb-2 mt-4 text-[13px] font-bold text-slate-700">موضوعات داغ</h3>
    <Chips rows={topics.slice(0, 6)} empty="موضوعی ثبت نشده است." />
  </DashboardCard>;
}
