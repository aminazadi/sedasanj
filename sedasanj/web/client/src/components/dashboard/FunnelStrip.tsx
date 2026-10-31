import { fmt } from "../../api";
import type { KpiDashboard } from "../../types";
import { Empty } from "../Widgets";
import { DashboardCard, Segmented } from "./DashboardCard";

export type FunnelView = "engagement" | "sales";

const LABELS: Record<string, string> = { all_calls: "کل تماس‌ها", effective: "تماس مؤثر", opportunities: "فرصت فروش", qualified: "واجد شرایط", interested: "علاقه‌مند", follow_up: "پیگیری", proposal: "پیشنهاد", won: "فروش" };
const HINTS: Record<FunnelView, string> = {
  engagement: "از تماس پاسخ‌داده‌شده تا فروش؛ هر مرحله زیرمجموعهٔ مرحلهٔ قبل است",
  sales: "مسیر فرصت‌های واجد شرایط تا فروش؛ باخت‌ها خارج از قیف شمرده می‌شوند",
};

/** Horizontal funnel; the stage that loses the most is marked so the manager knows where to look. */
export function FunnelStrip({ views, view, onView }: { views: KpiDashboard["funnel_views"]; view: FunnelView; onView: (value: FunnelView) => void }) {
  const rows = views[view];
  const first = Math.max(rows[0]?.count ?? 0, 1);
  const worst = rows.slice(1).reduce<number>((best, row, index) => ((row.drop_rate ?? -1) > (rows[best]?.drop_rate ?? -1) ? index + 1 : best), -1);
  return <DashboardCard title="از تماس تا فروش" hint={HINTS[view]} action={<Segmented label="نوع قیف" value={view} options={[{ value: "engagement", label: "تماس تا فروش" }, { value: "sales", label: "مراحل فروش" }]} onChange={onView} />}>
    {rows.length && rows[0].count ? <ol className="exec-funnel" style={{ gridTemplateColumns: `repeat(${rows.length}, minmax(0, 1fr))` }}>
      {rows.map((row, index) => <li key={row.key} className={index === worst ? "is-worst" : undefined}>
        <span className="text-xs text-slate-500">{LABELS[row.key] ?? row.key}</span>
        <strong className="exec-funnel__value">{fmt.int(row.count)}</strong>
        <span className="exec-funnel__bar" style={{ width: `${Math.max(4, (row.count * 100) / first)}%`, opacity: 1 - index * (0.5 / Math.max(rows.length - 1, 1)) }} aria-hidden="true" />
        <span className="mt-2 text-[11px] text-slate-500">{index === 0 ? "مبدأ" : `${row.pass_rate == null ? "—" : `${fmt.decimal(row.pass_rate)}٪`} عبور`}{index === worst ? <b className="ms-1 font-bold text-[#8a4b3f]">· بیشترین ریزش</b> : null}</span>
      </li>)}
    </ol> : <Empty />}
  </DashboardCard>;
}
