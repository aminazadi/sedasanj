import { Link } from "react-router-dom";
import { fmt } from "../../api";
import type { KpiDashboard } from "../../types";
import { Empty } from "../Widgets";
import { DashboardCard } from "./DashboardCard";

const QUALITY_ALERT = 70;

function QualityTrend({ current, previous }: { current: number | null; previous: number | null }) {
  if (current == null || previous == null) return <span className="text-slate-400">—</span>;
  const change = current - previous;
  if (Math.abs(change) < 1) return <span className="text-slate-400" title="بدون تغییر محسوس">—</span>;
  return <span className={change > 0 ? "text-brand-700" : "text-[#8a4b3f]"} title={`دورهٔ قبل ${fmt.decimal(previous)}`}>{change > 0 ? "▲" : "▼"} {fmt.decimal(Math.abs(change))}</span>;
}

/** Leaderboard by sales; low-sample operators are tagged rather than hidden. */
export function TeamPanel({ operators, total }: { operators: KpiDashboard["operators"]; total: number }) {
  const ranked = [...operators].sort((a, b) => b.wins - a.wins || (b.conversion.value ?? -1) - (a.conversion.value ?? -1) || b.calls - a.calls).slice(0, 6);
  const maxWins = Math.max(1, ...ranked.map((item) => item.wins));
  return <DashboardCard title="تیم" hint={`رتبه بر اساس فروش · ${fmt.int(total)} اپراتور فعال در این بازه`} action={<Link to="/operator-scores" className="exec-link">کارنامهٔ اپراتورها</Link>}>
    {ranked.length ? <div className="overflow-x-auto"><table className="exec-table min-w-[520px]">
      <thead><tr><th className="w-10" /><th>اپراتور</th><th>تماس</th><th>فروش</th><th>تبدیل</th><th>کیفیت</th><th>تغییر کیفیت</th></tr></thead>
      <tbody>{ranked.map((item, index) => <tr key={item.operator_id}>
        <td><span className="exec-rank">{fmt.int(index + 1)}</span></td>
        <td className="max-w-[12rem]"><span className="block truncate">{item.operator_label}</span>{item.sample_sufficient ? null : <span className="exec-tag">نمونهٔ کم</span>}</td>
        <td className="tabular-nums">{fmt.int(item.calls)}</td>
        <td className="tabular-nums"><span className="inline-flex items-center gap-2"><i className="exec-minibar" style={{ width: `${(item.wins * 48) / maxWins}px` }} aria-hidden="true" />{fmt.int(item.wins)}</span></td>
        <td className="tabular-nums">{item.conversion.value == null ? "—" : `${fmt.decimal(item.conversion.value)}٪`}</td>
        <td className="tabular-nums" style={{ color: item.quality_score != null && item.quality_score < QUALITY_ALERT ? "#8a4b3f" : undefined }}>{item.quality_score == null ? "—" : fmt.decimal(item.quality_score)}</td>
        <td className="tabular-nums"><QualityTrend current={item.quality_score} previous={item.previous_quality_score} /></td>
      </tr>)}</tbody>
    </table></div> : <Empty>هنوز تماسی به اپراتورها منتسب نشده است.</Empty>}
  </DashboardCard>;
}

/** What to keep doing and what to improve, from the scoring rubric. */
export function CoachingPanel({ coaching, title = "مربی‌گری من" }: { coaching: KpiDashboard["coaching"]; title?: string }) {
  const list = (rows: KpiDashboard["coaching"]["strengths"], tone: string) => rows.length ? <ul className="space-y-2">{rows.map((item) => <li key={`${item.call_id}-${item.title}`}><Link to={`/calls/${item.call_id}`} className="flex items-center justify-between gap-3 border-b border-[color:var(--line)] py-2 text-sm hover:text-brand-700"><span className="truncate">{item.title}</span><strong className="tabular-nums" style={{ color: tone }}>{fmt.decimal(item.average)}</strong></Link></li>)}</ul> : <p className="text-xs text-slate-500">هنوز امتیازی ثبت نشده است.</p>;
  return <DashboardCard title={title} hint="بر اساس معیارهای امتیازدهی تماس‌های این بازه">
    <div className="grid gap-6 sm:grid-cols-2"><div><h3 className="mb-2 text-sm font-bold text-brand-700">نقاط قوت</h3>{list(coaching.strengths, "#4b6e48")}</div><div><h3 className="mb-2 text-sm font-bold text-[#8a4b3f]">اولویت‌های بهبود</h3>{list(coaching.improvements, "#8a4b3f")}</div></div>
  </DashboardCard>;
}
