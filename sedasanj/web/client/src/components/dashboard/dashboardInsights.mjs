// Pure helpers behind the executive dashboard: period-over-period signals, the plain-language
// summary sentence and attention grouping. Kept framework-free so node tests can import it.

const numberFormat = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 });
const integerFormat = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 });

/** Relative change in percent; null when the previous period has nothing to compare against. */
export function relativeChange(current, previous) {
  if (current == null || previous == null || previous <= 0) return null;
  return Math.round(((current - previous) * 1000) / previous) / 10;
}

/** Minimum change that is worth mentioning: 5% for counts, 1 point for rates and scores. */
const SIGNIFICANT = { percent: 5, points: 1 };

const SIGNAL_TEXT = {
  wins: { up: (v) => `فروش ${v}٪ رشد کرد`, down: (v) => `فروش ${v}٪ کاهش یافت` },
  revenue: { up: (v) => `ارزش فروش ${v}٪ بیشتر شد`, down: (v) => `ارزش فروش ${v}٪ کمتر شد` },
  conversion: { up: (v) => `نرخ تبدیل ${v} واحد بهتر شد`, down: (v) => `نرخ تبدیل ${v} واحد افت کرد` },
  answer_rate: { up: (v) => `نرخ پاسخ‌دهی ${v} واحد بهتر شد`, down: (v) => `نرخ پاسخ‌دهی ${v} واحد افت کرد` },
  satisfaction: { up: (v) => `رضایت مشتری ${v} واحد بالا رفت`, down: (v) => `رضایت مشتری ${v} واحد پایین آمد` },
  quality: { up: (v) => `کیفیت مکالمه ${v} امتیاز بهتر شد`, down: (v) => `کیفیت مکالمه ${v} امتیاز افت کرد` },
  follow_up: { up: (v) => `پیگیری به‌موقع ${v} واحد بهتر شد`, down: (v) => `پیگیری به‌موقع ${v} واحد عقب افتاد` },
};

/** Weight of each signal when deciding the overall tone; sales outcomes matter most. */
const WEIGHT = { wins: 3, revenue: 3, conversion: 2, answer_rate: 2, satisfaction: 2, quality: 1, follow_up: 1 };

/** Every comparable headline metric with its change and whether the move is good news. */
export function buildSignals(cards, { operator = false } = {}) {
  const signals = [
    { key: "wins", unit: "percent", change: relativeChange(cards.explicit_wins, cards.previous_explicit_wins) },
    { key: "conversion", unit: "points", change: cards.ai_win_rate?.change ?? null },
    { key: "answer_rate", unit: "points", change: cards.answer_rate?.change ?? null },
    { key: "satisfaction", unit: "points", change: cards.satisfaction_rate?.change ?? null },
    {
      key: "quality",
      unit: "points",
      change: cards.quality_score != null && cards.previous_quality_score != null ? Math.round((cards.quality_score - cards.previous_quality_score) * 10) / 10 : null,
    },
    { key: "follow_up", unit: "points", change: cards.follow_up_sla_rate?.change ?? null },
  ];
  if (!operator && cards.currency) signals.push({ key: "revenue", unit: "percent", change: relativeChange(cards.revenue, cards.previous_revenue) });
  return signals
    .filter((item) => item.change != null)
    .map((item) => ({ ...item, significant: Math.abs(item.change) >= SIGNIFICANT[item.unit], weight: WEIGHT[item.key] }));
}

function phrase(signal) {
  const text = SIGNAL_TEXT[signal.key];
  const value = numberFormat.format(Math.abs(signal.change));
  return signal.change > 0 ? text.up(value) : text.down(value);
}

/** Business priority of each action type; lower comes first within the same severity. */
const ACTION_PRIORITY = {
  hot_opportunity: 0,
  overdue_follow_up: 1,
  operator_quality_drop: 2,
  kpi_decline: 3,
  objection_surge: 4,
  angry_customer: 5,
  missed_peak: 6,
  needs_review: 9,
};

/** Groups dashboard actions by type: urgent groups first, then business priority, then size. */
export function groupActions(actions) {
  const groups = new Map();
  for (const action of actions) {
    const group = groups.get(action.type) ?? { type: action.type, severity: action.severity, count: 0, items: [] };
    group.count += 1;
    group.items.push(action);
    if (action.severity === "high") group.severity = "high";
    groups.set(action.type, group);
  }
  const priority = (type) => ACTION_PRIORITY[type] ?? 8;
  return [...groups.values()].sort((a, b) => Number(b.severity === "high") - Number(a.severity === "high") || priority(a.type) - priority(b.type) || b.count - a.count);
}

const ATTENTION_TEXT = {
  hot_opportunity: (n) => `${n} فرصت داغ هنوز پیگیری ندارد`,
  overdue_follow_up: (n) => `${n} پیگیری از موعد گذشته`,
  operator_quality_drop: (n) => `کیفیت مکالمهٔ ${n} اپراتور افت کرده`,
  angry_customer: (n) => `${n} مشتری عصبانی بدون پیگیری مانده`,
};

/**
 * One-line verdict for the period plus a short attention line.
 * tone: good | bad | mixed | steady | unknown (no comparable previous period).
 */
export function summarize(cards, actions, options = {}) {
  const signals = buildSignals(cards, options);
  const significant = signals.filter((item) => item.significant);
  const good = significant.filter((item) => item.change > 0).sort((a, b) => b.weight - a.weight || Math.abs(b.change) - Math.abs(a.change));
  const bad = significant.filter((item) => item.change < 0).sort((a, b) => b.weight - a.weight || Math.abs(b.change) - Math.abs(a.change));
  const score = good.reduce((sum, item) => sum + item.weight, 0) - bad.reduce((sum, item) => sum + item.weight, 0);
  let tone;
  let headline;
  if (!signals.length) {
    tone = "unknown";
    headline = cards.total_calls ? `${integerFormat.format(cards.total_calls)} تماس در این بازه ثبت شد؛ دورهٔ قبل دادهٔ کافی برای مقایسه ندارد.` : "در این بازه هنوز تماسی ثبت نشده است.";
  } else if (!significant.length) {
    tone = "steady";
    headline = "دورهٔ باثباتی بود؛ شاخص‌های اصلی تقریباً مثل دورهٔ قبل مانده‌اند.";
  } else {
    tone = good.length && bad.length ? (score > 0 ? "good" : score < 0 ? "bad" : "mixed") : good.length ? "good" : "bad";
    const lead = tone === "good" ? "دورهٔ خوبی بود" : tone === "bad" ? "دورهٔ پرچالشی بود" : "دورهٔ دوگانه‌ای بود";
    const best = tone === "bad" ? bad[0] : good[0] ?? bad[0];
    const counter = tone === "bad" ? good[0] : bad[0];
    headline = `${lead}؛ ${phrase(best)}${counter ? `، اما ${phrase(counter)}` : ""}.`;
  }
  const attention = groupActions(actions)
    .filter((group) => ATTENTION_TEXT[group.type])
    .slice(0, 2)
    .map((group) => ATTENTION_TEXT[group.type](integerFormat.format(group.count)));
  const detail = attention.length ? `${attention.join(" و ")}.` : null;
  return { tone, headline, detail, signals };
}
