import assert from "node:assert/strict";
import test from "node:test";
import { buildSignals, groupActions, relativeChange, summarize } from "../src/components/dashboard/dashboardInsights.mjs";

const rate = (value, change) => ({ value, change, numerator: 0, denominator: 0 });
const baseCards = {
  total_calls: 120,
  explicit_wins: 0,
  previous_explicit_wins: 0,
  ai_win_rate: rate(null, null),
  answer_rate: rate(null, null),
  satisfaction_rate: rate(null, null),
  follow_up_sla_rate: rate(null, null),
  quality_score: null,
  previous_quality_score: null,
  revenue: 0,
  previous_revenue: 0,
  currency: null,
};

test("relative change needs a positive previous value", () => {
  assert.equal(relativeChange(118, 100), 18);
  assert.equal(relativeChange(5, 0), null);
  assert.equal(relativeChange(null, 10), null);
});

test("signals skip metrics without a comparable previous period", () => {
  const signals = buildSignals({ ...baseCards, explicit_wins: 118, previous_explicit_wins: 100, answer_rate: rate(87, -3.1) });
  assert.deepEqual(signals.map((item) => [item.key, item.change, item.significant]), [["wins", 18, true], ["answer_rate", -3.1, true]]);
});

test("revenue counts only for managers with CRM currency", () => {
  const cards = { ...baseCards, revenue: 150, previous_revenue: 100, currency: "IRT" };
  assert.ok(buildSignals(cards).some((item) => item.key === "revenue"));
  assert.ok(!buildSignals(cards, { operator: true }).some((item) => item.key === "revenue"));
});

test("summary names the best news and the main concern", () => {
  const cards = { ...baseCards, explicit_wins: 118, previous_explicit_wins: 100, answer_rate: rate(87, -3.1) };
  const actions = [
    { type: "hot_opportunity", severity: "high", call_id: "a", title: "", due_at: null },
    { type: "hot_opportunity", severity: "high", call_id: "b", title: "", due_at: null },
  ];
  const result = summarize(cards, actions);
  assert.equal(result.tone, "good");
  assert.match(result.headline, /^دورهٔ خوبی بود؛ فروش ۱۸٪ رشد کرد، اما نرخ پاسخ‌دهی ۳٫۱ واحد افت کرد\.$/);
  assert.equal(result.detail, "۲ فرصت داغ هنوز پیگیری ندارد.");
});

test("summary reports a steady or unknown period honestly", () => {
  assert.equal(summarize({ ...baseCards, answer_rate: rate(90, 0.4) }, []).tone, "steady");
  const unknown = summarize(baseCards, []);
  assert.equal(unknown.tone, "unknown");
  assert.match(unknown.headline, /۱۲۰ تماس/);
  assert.equal(summarize({ ...baseCards, total_calls: 0 }, []).headline, "در این بازه هنوز تماسی ثبت نشده است.");
});

test("summary leads with bad news when losses outweigh gains", () => {
  const cards = { ...baseCards, explicit_wins: 70, previous_explicit_wins: 100, follow_up_sla_rate: rate(92, 4) };
  const result = summarize(cards, []);
  assert.equal(result.tone, "bad");
  assert.match(result.headline, /^دورهٔ پرچالشی بود؛ فروش ۳۰٪ کاهش یافت، اما پیگیری به‌موقع ۴ واحد بهتر شد\.$/);
});

test("action groups put urgent types first, then business priority, then size", () => {
  const groups = groupActions([
    { type: "needs_review", severity: "normal" },
    { type: "needs_review", severity: "normal" },
    { type: "needs_review", severity: "normal" },
    { type: "angry_customer", severity: "normal" },
    { type: "overdue_follow_up", severity: "high" },
    { type: "overdue_follow_up", severity: "high" },
    { type: "overdue_follow_up", severity: "high" },
    { type: "hot_opportunity", severity: "high" },
    { type: "custom_alert", severity: "normal" },
    { type: "custom_alert", severity: "normal" },
  ]);
  assert.deepEqual(groups.map((group) => [group.type, group.count]), [["hot_opportunity", 1], ["overdue_follow_up", 3], ["angry_customer", 1], ["custom_alert", 2], ["needs_review", 3]]);
});
