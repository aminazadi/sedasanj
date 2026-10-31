import { fmt } from "../../api";
import type { KpiDashboard } from "../../types";
import { relativeChange, summarize } from "./dashboardInsights.mjs";
import { DeltaBadge } from "./KpiTiles";

/** Hero band: plain-language verdict for the period and the three numbers a manager asks first. */
export function ExecutiveSummary({ data, operator }: { data: KpiDashboard; operator: boolean }) {
  const c = data.cards;
  const summary = summarize(c, data.actions, { operator });
  const rateText = (value: number | null) => (value == null ? "—" : `${fmt.decimal(value)}٪`);
  const pills = [
    { label: operator ? "فروش من" : "فروش", value: fmt.int(c.explicit_wins), delta: <DeltaBadge change={relativeChange(c.explicit_wins, c.previous_explicit_wins)} unit="percent" /> },
    { label: operator ? "نرخ تبدیل من" : "نرخ تبدیل", value: rateText(c.ai_win_rate.value), delta: <DeltaBadge change={c.ai_win_rate.change ?? null} unit="points" /> },
    { label: "رضایت مشتری", value: rateText(c.satisfaction_rate.value), delta: <DeltaBadge change={c.satisfaction_rate.change ?? null} unit="points" /> },
  ];
  return <section className={`exec-hero exec-hero--${summary.tone}`} aria-live="polite">
    <div className="exec-hero__text">
      <h2>{summary.headline}</h2>
      {summary.detail ? <p>{summary.detail}</p> : <p>موردی که فوراً به توجه شما نیاز داشته باشد ثبت نشده است.</p>}
    </div>
    <dl className="exec-hero__pills">
      {pills.map((pill) => <div key={pill.label}><dt>{pill.label}</dt><dd><span className="exec-hero__value">{pill.value}</span>{pill.delta}</dd></div>)}
    </dl>
  </section>;
}
