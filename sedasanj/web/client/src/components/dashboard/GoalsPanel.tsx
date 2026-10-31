import { Link } from "react-router-dom";
import { fmt } from "../../api";
import type { KpiDashboard } from "../../types";
import { DashboardCard } from "./DashboardCard";

const GOAL_LABELS: Record<string, string> = { conversion_rate: "نرخ تبدیل", quality_score: "کیفیت مکالمه", follow_up_sla_rate: "پیگیری در SLA" };
const PERCENT_GOALS = new Set(["conversion_rate", "follow_up_sla_rate"]);

/** Goal progress; all goals are rates or scores, so "on track" means the period average meets the target. */
export function GoalsPanel({ goals, canEdit }: { goals: KpiDashboard["cards"]["goal_achievement"]; canEdit: boolean }) {
  const settingsLink = canEdit ? <Link to="/account-settings?tab=kpi" className="exec-link">تنظیم اهداف</Link> : null;
  const value = (metric: string, number: number | null) => (number == null ? "—" : PERCENT_GOALS.has(metric) ? `${fmt.decimal(number)}٪` : fmt.decimal(number));
  return <DashboardCard title="پیشرفت اهداف" hint="میانگین این بازه در برابر هدف تعیین‌شده" action={settingsLink}>
    {goals.length ? <ul className="space-y-4">
      {goals.map((goal) => {
        const achievement = goal.achievement ?? 0;
        const reached = goal.actual != null && achievement >= 100;
        const daysLeft = Math.ceil((new Date(goal.valid_to).getTime() - Date.now()) / 86400000);
        return <li key={goal.metric}>
          <div className="mb-2 flex items-baseline justify-between gap-3 text-sm"><span className="text-slate-700">{GOAL_LABELS[goal.metric] ?? goal.metric}</span><span className="tabular-nums"><strong className="font-bold text-slate-800">{value(goal.metric, goal.actual)}</strong><span className="text-slate-500"> از {value(goal.metric, goal.target)}</span></span></div>
          <div className="exec-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(Math.min(achievement, 100))} aria-label={GOAL_LABELS[goal.metric] ?? goal.metric}><i style={{ width: `${Math.min(achievement, 100)}%`, background: reached ? "#4b6e48" : "#a78a6c" }} /></div>
          <div className="mt-1.5 flex justify-between text-[11px] text-slate-500"><span>{goal.actual == null ? "دادهٔ کافی برای سنجش نیست" : `${fmt.int(achievement)}٪ محقق`}</span><span style={{ color: reached ? "#4b6e48" : "#8a4b3f" }}>{reached ? "به هدف رسیده" : daysLeft > 0 ? `${fmt.int(daysLeft)} روز تا پایان دورهٔ هدف` : "زیر هدف"}</span></div>
        </li>;
      })}
    </ul> : <div className="border border-dashed border-[color:var(--line-strong)] p-5 text-center text-sm leading-7 text-slate-500">
      <p>هنوز هدفی برای این بازه تعریف نشده است.</p>
      {canEdit ? <Link to="/account-settings?tab=kpi" className="btn mt-3 inline-flex">تعریف هدف</Link> : <p className="text-xs">تعریف هدف با مدیر سازمان است.</p>}
    </div>}
  </DashboardCard>;
}
