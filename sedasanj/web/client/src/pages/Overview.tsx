import { useMemo } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Icon } from "@iconify/react";
import checkMarkButtonIcon from "@iconify-icons/lucide/circle-check";
import { chart } from "@cbi/web-shared/theme";
import { FilterSelect, useFilterBar, type FilterBarField } from "@cbi/web-shared/components/FilterBar";
import { DateRangePicker } from "../components/DateRangePicker";
import { PageHeader } from "../components/PageHeader";
import { EMPTY_STATE_ART } from "../components/pageArt";
import { TopicsCloud } from "../components/TopicsCloud";
import { fmt, query, request } from "../api";
import { isOperator, isOrgAdmin, useAuth } from "../auth";
import { Empty, ErrorBox, Pagination, SentimentBadge, Stat, StatusBadge, SummaryCell, TrajectoryBadge } from "../components/Widgets";
import type { CallPage, KpiDashboard, RateMetric } from "../types";
import { Skeleton, SkeletonBreakdown, SkeletonRegion, SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { AttentionPanel } from "../components/dashboard/AttentionPanel";
import { DashboardCard } from "../components/dashboard/DashboardCard";
import { ExecutiveSkeleton } from "../components/dashboard/ExecutiveSkeleton";
import { ExecutiveSummary } from "../components/dashboard/ExecutiveSummary";
import { FunnelStrip, type FunnelView } from "../components/dashboard/FunnelStrip";
import { GoalsPanel } from "../components/dashboard/GoalsPanel";
import { DeltaBadge, KpiTile } from "../components/dashboard/KpiTiles";
import { CoachingPanel, TeamPanel } from "../components/dashboard/TeamPanel";
import { TREND_METRICS, TrendPanel, type TrendMetric } from "../components/dashboard/TrendPanel";
import { VoiceOfCustomer } from "../components/dashboard/VoiceOfCustomer";
import { relativeChange } from "../components/dashboard/dashboardInsights.mjs";

function rangeDates(range: string, from: string, to: string) {
  if (range === "custom" && from && to) return { from: new Date(`${from}T00:00:00`).toISOString(), to: new Date(`${to}T23:59:59.999`).toISOString() };
  const end = new Date();
  return { from: new Date(end.getTime() - (Number(range) || 30) * 86400000).toISOString(), to: end.toISOString() };
}
function pct(metric: RateMetric) { return metric.value == null ? "—" : `${fmt.decimal(metric.value)}٪`; }
function delta(metric: RateMetric) { return metric.change == null ? "دورهٔ قبل داده کافی ندارد" : `${metric.change > 0 ? "+" : ""}${fmt.decimal(metric.change)} واحد نسبت به دورهٔ قبل`; }
/** Large amounts in words-friendly units so six-tile rows stay readable. */
function compactAmount(value: number) {
  if (Math.abs(value) >= 1e9) return { value: fmt.decimal(value / 1e9), unit: "میلیارد" };
  if (Math.abs(value) >= 1e6) return { value: fmt.decimal(value / 1e6), unit: "میلیون" };
  return { value: fmt.int(value), unit: "" };
}

function DashboardEmpty({ title = "موردی یافت نشد.", description = "با ثبت داده‌های بیشتر، جزئیات این بخش نمایش داده می‌شود.", success = false }: { title?: string; description?: string; success?: boolean }) {
  const icon = success ? checkMarkButtonIcon : null;
  return <div className="panel-empty">{icon ? <span className="mb-3 flex h-14 w-14 items-center justify-center border border-current bg-emerald-50 text-emerald-700"><Icon icon={icon} className="h-7 w-7" /></span> : <img className="panel-empty__art" src={EMPTY_STATE_ART} alt="" aria-hidden="true" loading="lazy" decoding="async" />}<strong className={success ? "text-sm text-emerald-800" : "text-sm text-slate-700"}>{title}</strong><p className="mt-1 max-w-xs text-xs leading-6 text-slate-500">{description}</p></div>;
}

const CALL_TYPE_LABELS: Record<string, string> = {
  no_answer: "بدون پاسخ",
  busy: "مشغول",
  congestion: "اختلال مسیر",
  failed: "ناموفق",
  canceled: "لغوشده",
};
const CALL_TYPE_COLORS: Record<string, string> = {
  no_answer: chart.danger,
  busy: chart.warning,
  congestion: chart.cyan,
  failed: chart.secondary,
  canceled: chart.light,
};

function CallTypeChart({ items }: { items: Array<{ key: string; count: number }> }) {
  const rows = items.filter((item) => item.count > 0).map((item) => ({
    ...item,
    label: CALL_TYPE_LABELS[item.key] ?? item.key,
  }));
  if (!rows.length) return <Empty />;
  return <div className="h-64 min-w-0 sm:h-72" dir="ltr"><ResponsiveContainer width="100%" height="100%"><BarChart data={rows} layout="vertical" margin={{ top: 8, right: 12, bottom: 4, left: 16 }}><CartesianGrid stroke={chart.light} strokeDasharray="3 5" horizontal={false} /><XAxis type="number" allowDecimals={false} tickFormatter={fmt.int} tick={{ fill: "#64748b", fontSize: 12 }} tickLine={false} axisLine={false} /><YAxis type="category" dataKey="label" width={110} tick={{ fill: "#64748b", fontSize: 12 }} tickLine={false} axisLine={false} /><Tooltip contentStyle={{ border: "1px solid #b2ac88", borderRadius: 0, direction: "rtl", fontSize: 12 }} formatter={(value: number) => [fmt.int(value), "تماس"]} /><Bar dataKey="count" name="تماس">{rows.map((item) => <Cell key={item.key} fill={CALL_TYPE_COLORS[item.key] ?? chart.danger} />)}</Bar></BarChart></ResponsiveContainer></div>;
}

function Breakdown({ title, rows }: { title: string; rows: Array<[string, number]> }) {
  const max = Math.max(1, ...rows.map((row) => row[1]));
  return <section className="min-w-0 bg-[#F2F0EF] p-5"><h3 className="mb-4 text-sm font-bold text-slate-800">{title}</h3>{rows.length ? <div className="space-y-3">{rows.map(([label, count]) => <div key={label}><div className="mb-1 flex items-center justify-between gap-3 text-xs"><span className="truncate text-slate-700">{label}</span><strong className="shrink-0 text-slate-600">{fmt.int(count)}</strong></div><div className="h-1.5 overflow-hidden bg-slate-100"><div className="h-full bg-brand-500" style={{ width: `${count * 100 / max}%` }} /></div></div>)}</div> : <DashboardEmpty title="داده کافی وجود ندارد." description="پس از تکمیل تحلیل تماس‌ها، این بخش نمایش داده می‌شود." />}</section>;
}

interface ViewContext {
  operator: boolean;
  operatorOffset: number;
  campaignOffset: number;
  tableLimit: number;
  selectedRange: { from: string; to: string };
  navigate: (to: string) => void;
  updateAnalysisFilter: (key: string, value: string, clearKey?: string) => void;
}

/** Headline KPI row: volume, reach, pipeline, quality, follow-up discipline and money. */
function KpiRow({ data, operator, range }: { data: KpiDashboard; operator: boolean; range: { from: string; to: string } }) {
  const c = data.cards;
  const days = Math.max(1, Math.round((new Date(data.to_date).getTime() - new Date(data.from_date).getTime()) / 86400000));
  const sla = c.follow_up_sla_rate;
  const revenue = compactAmount(c.revenue);
  const pipeline = compactAmount(c.pipeline_value);
  const qualityChange = c.quality_score != null && c.previous_quality_score != null ? c.quality_score - c.previous_quality_score : null;
  return <div className="exec-kpis">
    <KpiTile label="کل تماس‌ها" value={fmt.int(c.total_calls)} foot={`${fmt.decimal(c.total_calls / days)} در روز`} delta={<DeltaBadge change={relativeChange(c.total_calls, c.previous_total_calls)} unit="percent" polarity="neutral" />} series={data.trend.map((item) => item.calls)} to={`/calls${query(range)}`} />
    <KpiTile label="نرخ پاسخ‌دهی" value={pct(c.answer_rate)} foot={`${fmt.int(c.missed_calls)} تماس بی‌پاسخ`} delta={<DeltaBadge change={c.answer_rate.change ?? null} unit="points" />} series={data.trend.map((item) => (item.calls ? (item.answered_calls * 100) / item.calls : null))} seriesTone={(c.answer_rate.change ?? 0) < 0 ? "bad" : "good"} to={`/calls${query({ ...range, status: "no_answer" })}`} />
    <KpiTile label="فرصت فروش" value={fmt.int(c.opportunities)} foot={`${fmt.int(c.probable_opportunities)} فرصت محتمل`} delta={<DeltaBadge change={relativeChange(c.opportunities, c.previous_opportunities)} unit="percent" />} series={data.trend.map((item) => item.opportunities)} />
    <KpiTile label="کیفیت مکالمه" value={c.quality_score == null ? "—" : fmt.decimal(c.quality_score)} unit={c.quality_score == null ? undefined : "از ۱۰۰"} foot={c.quality_score == null ? "نمونهٔ امتیازدهی کافی نیست" : "میانگین تماس‌های امتیازدهی‌شده"} delta={<DeltaBadge change={qualityChange} unit="score" />} series={data.trend.map((item) => item.quality_score)} seriesTone={(qualityChange ?? 0) < 0 ? "bad" : "good"} to="/operator-scores" />
    <KpiTile label="پیگیری به‌موقع" value={pct(sla)} foot={sla.denominator ? `${fmt.int(sla.numerator)} از ${fmt.int(sla.denominator)} کار سررسیده` : "کار سررسیده‌ای نیست"} delta={<DeltaBadge change={sla.change ?? null} unit="points" />} footer={<div className="exec-bar my-[13px]" aria-hidden="true"><i style={{ width: `${sla.value ?? 0}%` }} /></div>} to="/tasks" />
    {!operator && c.currency
      ? <KpiTile label="ارزش فروش" value={revenue.value} unit={`${revenue.unit} ${c.currency}`.trim()} foot={`پایپ‌لاین ${pipeline.value} ${pipeline.unit}`} delta={<DeltaBadge change={relativeChange(c.revenue, c.previous_revenue)} unit="percent" />} series={data.trend.map((item) => item.wins)} />
      : <KpiTile label={operator ? "فروش من" : "فروش قطعی"} value={fmt.int(c.explicit_wins)} foot={operator ? "فروش‌های صریح در تماس‌های من" : "ارزش ریالی با اتصال CRM نمایش داده می‌شود"} delta={<DeltaBadge change={relativeChange(c.explicit_wins, c.previous_explicit_wins)} unit="percent" />} series={data.trend.map((item) => item.wins)} />}
  </div>;
}

/** Secondary analyses kept below the executive view; built from the same payload. */
function detailView(data: KpiDashboard, recent: CallPage, ctx: ViewContext) {
  const { operator, operatorOffset, campaignOffset, tableLimit, selectedRange, navigate, updateAnalysisFilter } = ctx;
  const c = data.cards;
  const widgets = new Set(data.dashboard_widgets);
  const talk = [{ name: "اپراتور", value: c.talk_balance.agent_percent ?? 0, color: chart.primary }, { name: "مشتری", value: c.talk_balance.caller_percent ?? 0, color: chart.cyan }];
  return {
    stats: !operator ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><Stat title="تبدیل رسمی CRM" value={pct(c.crm_conversion_rate)} hint={delta(c.crm_conversion_rate)} /><Stat title="پایپ‌لاین" value={c.currency ? `${fmt.int(c.pipeline_value)} ${c.currency}` : "—"} hint={c.currency ? "فرصت‌های علاقه‌مند و در حال پیگیری" : "دادهٔ CRM کافی نیست"} /><Stat title="پوشش نتیجهٔ فروش" value={pct(c.outcome_coverage)} hint={`${fmt.int(c.unknown_outcomes)} فرصت با نتیجهٔ نامشخص`} /><Stat title="پیام صوتی" value={fmt.int(c.voicemail_calls)} hint={`${fmt.duration(c.voicemail_total_duration_ms)} مدت کل · ${fmt.decimal(c.voicemail_transcription_rate)}٪ رونویسی‌شده`} /></div> : null,
    voicemail: !operator ? <section className="card"><h2 className="font-bold">تفکیک پیام‌های صوتی بر اساس داخلی صندوق</h2><p className="mb-4 mt-1 text-sm text-slate-500">مدت میانگین هر پیام: {fmt.duration(c.voicemail_average_duration_ms)} · پیام‌های دارای متن: {fmt.int(c.voicemail_transcribed_calls)}</p>{data.voicemail_mailboxes.length ? <div className="flex flex-wrap gap-2">{data.voicemail_mailboxes.map((item) => <span key={item.mailbox} className="border border-[color:var(--line)] bg-[#F2F0EF] px-3 py-2 text-sm">داخلی {fmt.digits(item.mailbox)} <strong className="ms-2">{fmt.int(item.count)}</strong></span>)}</div> : <Empty />}</section> : null,
    callTypes: <section className="card"><h2 className="font-bold">توزیع نوع تماس‌های بی‌پاسخ</h2><p className="mb-4 mt-1 text-sm text-slate-500">تفکیک تماس‌های بدون پاسخ، مشغول، اختلال مسیر و سایر خطاهای نهایی</p><CallTypeChart items={data.call_types} /></section>,
    talkBalance: widgets.has("talk_balance") ? <section className="card"><h2 className="font-bold">تعادل گفت‌وگو</h2><p className="mb-4 mt-1 text-sm text-slate-500">سهم زمانی صحبت اپراتور و مشتری</p>{c.talk_balance.agent_percent == null ? <Empty /> : <div className="grid items-center gap-4 sm:grid-cols-2"><div className="h-64" dir="ltr"><ResponsiveContainer><PieChart><Pie data={talk} dataKey="value" nameKey="name" innerRadius={52} outerRadius={88} paddingAngle={3}>{talk.map((item) => <Cell key={item.name} fill={item.color} />)}</Pie><Tooltip formatter={(value: number) => `${fmt.decimal(value)}٪`} /><Legend /></PieChart></ResponsiveContainer></div><div className="space-y-3">{talk.map((item) => <div key={item.name} className="border border-[color:var(--line)] p-4"><p className="text-sm text-slate-500">{item.name}</p><strong className="mt-1 block text-2xl">{fmt.decimal(item.value)}٪</strong></div>)}</div></div>}</section> : null,
    tasks: widgets.has("tasks") ? <section className="card"><div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold">وضعیت کارهای قابل پیگیری</h2><p className="mt-1 text-sm text-slate-500">کارهای منتسب به تماس‌های این بازه</p></div><Link to="/tasks" className="btn-ghost inline-flex h-9 items-center px-3 py-0 text-xs">مشاهدهٔ همه کارها</Link></div><div className="grid grid-cols-2 gap-px border border-[color:var(--line)] bg-[color:var(--line)] text-center sm:grid-cols-4">{[["نرخ تکمیل", pct(c.task_summary.completion_rate), "text-brand-700"], ["انجام‌شده", fmt.int(c.task_summary.done), "text-slate-800"], ["باز", fmt.int(c.task_summary.open), "text-[#8f7d3c]"], ["عقب‌افتاده", fmt.int(c.task_summary.overdue), "text-[#8a4b3f]"]].map(([label, value, tone]) => <div key={label} className="bg-[#F2F0EF] p-4"><strong className={`block text-2xl font-light tabular-nums ${tone}`}>{value}</strong><span className="text-xs text-slate-500">{label}</span></div>)}</div><p className="mt-3 text-xs text-slate-500">{delta(c.task_summary.completion_rate)}</p></section> : null,
    coaching: widgets.has("coaching") && !operator ? <CoachingPanel coaching={data.coaching} title="نقاط قوت و اولویت‌های بهبود تیم" /> : null,
    operatorsTable: !operator ? <section className="card overflow-x-auto"><h2 className="mb-4 font-bold">عملکرد تفصیلی اپراتورها</h2><table className="table min-w-[780px]"><thead><tr><th>اپراتور</th><th>تماس پاسخ‌داده‌شده</th><th>تماس بی‌پاسخ</th><th>فرصت</th><th>فروش</th><th>تبدیل</th><th>کیفیت</th><th>سهم صحبت</th><th>نمونه</th></tr></thead><tbody>{data.operators.map((item) => <tr key={item.operator_id}><td>{item.operator_label}</td><td>{fmt.int(item.calls)}</td><td>{fmt.int(item.missed_calls)}</td><td>{fmt.int(item.opportunities)}</td><td>{fmt.int(item.wins)}</td><td>{pct(item.conversion)}</td><td>{item.quality_score == null ? "—" : fmt.decimal(item.quality_score)}</td><td>{item.agent_talk_ratio == null ? "—" : `${fmt.decimal(item.agent_talk_ratio)}٪`}</td><td className={item.sample_sufficient ? "text-emerald-700" : "text-amber-700"}>{item.sample_sufficient ? "کافی" : "ناکافی"}</td></tr>)}</tbody></table><Pagination page={Math.floor(operatorOffset / tableLimit) + 1} hasPrevious={operatorOffset > 0} hasNext={operatorOffset + tableLimit < data.operators_total} total={data.operators_total} onPrevious={() => updateAnalysisFilter("operator_offset", String(Math.max(0, operatorOffset - tableLimit)))} onNext={() => updateAnalysisFilter("operator_offset", String(operatorOffset + tableLimit))} /></section> : null,
    campaignsTable: !operator ? <section className="card overflow-x-auto"><h2 className="mb-4 font-bold">کمپین‌ها و منابع</h2><table className="table min-w-[600px]"><thead><tr><th>کمپین / منبع</th><th>تماس</th><th>فرصت</th><th>فروش</th><th>نرخ برد AI</th></tr></thead><tbody>{data.breakdowns.campaigns.map((item) => <tr key={item.key}><td>{item.key === "unknown" ? "منبع نامشخص" : item.key}</td><td>{fmt.int(item.calls)}</td><td>{fmt.int(item.opportunities)}</td><td>{fmt.int(item.wins)}</td><td>{pct(item.conversion)}</td></tr>)}</tbody></table><Pagination page={Math.floor(campaignOffset / tableLimit) + 1} hasPrevious={campaignOffset > 0} hasNext={campaignOffset + tableLimit < data.breakdowns.campaigns_total} total={data.breakdowns.campaigns_total} onPrevious={() => updateAnalysisFilter("campaign_offset", String(Math.max(0, campaignOffset - tableLimit)))} onNext={() => updateAnalysisFilter("campaign_offset", String(campaignOffset + tableLimit))} /></section> : null,
    recent: <section className="card overflow-x-auto"><div className="mb-3 flex items-center justify-between"><div><h2 className="font-bold">تماس‌های اخیر بازه</h2><p className="mt-1 text-sm text-slate-500">برای بررسی کامل، روی هر ردیف کلیک کنید.</p></div><Link to={`/calls${query({ from: selectedRange.from, to: selectedRange.to })}`} className="btn-ghost inline-flex h-9 items-center px-3 py-0 text-xs">همه تماس‌ها</Link></div>{recent.items.length ? <table className="table min-w-[780px]"><thead><tr><th>زمان</th><th>شماره</th><th>مدت</th><th>خلاصه</th><th>وضعیت</th><th>احساس</th><th>تغییر</th></tr></thead><tbody>{recent.items.map((call) => <tr key={call.id} className="table-row-link" role="link" tabIndex={0} onClick={() => navigate(`/calls/${call.id}`)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); navigate(`/calls/${call.id}`); } }}><td>{fmt.dateTime(call.started_at)}</td><td dir="ltr">{call.caller_number ? fmt.digits(call.caller_number) : "—"}</td><td>{fmt.duration(call.duration_ms)}</td><SummaryCell summary={call.summary} /><td><StatusBadge status={call.call_type === "answered" ? call.status : call.call_type} /></td><td><SentimentBadge sentiment={call.sentiment} /></td><td><TrajectoryBadge trajectory={call.sentiment_trajectory} /></td></tr>)}</tbody></table> : <Empty />}</section>,
    breakdowns: <div className="grid gap-px overflow-hidden border border-[color:var(--line)] bg-[#B2AC88] lg:grid-cols-2"><Breakdown title="اعتراض‌های پرتکرار" rows={data.breakdowns.objections} /><Breakdown title="محصولات و خدمات" rows={data.breakdowns.products} /><TopicsCloud rows={data.breakdowns.topics} emptyState={<DashboardEmpty title="داده کافی وجود ندارد." description="پس از تکمیل تحلیل تماس‌ها، این بخش نمایش داده می‌شود." />} /><Breakdown title="دلایل برد و باخت" rows={data.breakdowns.win_loss_reasons} /></div>,
  };
}

const DEFAULT_WIDGETS = ["trend", "funnel", "sentiment", "operator_comparison", "talk_balance", "tasks", "coaching", "actions"];
const EMPTY_FILTERS: KpiDashboard["filters"] = { directions: [], campaigns: [], sources: [], intents: [], certainties: [], teams: [], operators: [] };

const OPERATOR_COLUMNS: SkeletonColumn[] = [
  { label: "اپراتور", width: "7rem" }, { label: "تماس پاسخ‌داده‌شده", width: "2rem" }, { label: "تماس بی‌پاسخ", width: "2rem" },
  { label: "فرصت", width: "2rem" }, { label: "فروش", width: "2rem" }, { label: "تبدیل", width: "3rem" }, { label: "کیفیت", width: "2.5rem" },
  { label: "سهم صحبت", width: "3rem" }, { label: "نمونه", width: "3rem" },
];
const CAMPAIGN_COLUMNS: SkeletonColumn[] = [
  { label: "کمپین / منبع", width: "8rem" }, { label: "تماس", width: "2rem" }, { label: "فرصت", width: "2rem" },
  { label: "فروش", width: "2rem" }, { label: "نرخ برد AI", width: "3rem" },
];
const RECENT_COLUMNS: SkeletonColumn[] = [
  { label: "زمان", width: "8.5rem" }, { label: "شماره", width: "6.5rem", dir: "ltr" }, { label: "مدت", width: "2.5rem" },
  { label: "خلاصه", width: "16rem", cellClassName: "max-w-sm truncate" }, { label: "وضعیت", kind: "badge" },
  { label: "احساس", kind: "badge" }, { label: "تغییر", kind: "badge" },
];

function DetailsSkeleton({ operator, previous }: { operator: boolean; previous: KpiDashboard | undefined }) {
  return (
    <SkeletonRegion>
      <div className="grid gap-px overflow-hidden border border-[color:var(--line)] bg-[#B2AC88] lg:grid-cols-2"><SkeletonBreakdown title="اعتراض‌های پرتکرار" rows={previous?.breakdowns.objections.length || 5} /><SkeletonBreakdown title="محصولات و خدمات" rows={previous?.breakdowns.products.length || 5} /><section className="min-w-0 bg-[#F2F0EF] p-5" aria-hidden="true"><h3 className="mb-4 text-sm font-bold text-slate-800">موضوعات پرتکرار</h3><Skeleton className="min-h-44 w-full" /></section><SkeletonBreakdown title="دلایل برد و باخت" rows={previous?.breakdowns.win_loss_reasons.length || 5} /></div>
      {!operator ? <section className="card overflow-x-auto"><h2 className="mb-4 font-bold">عملکرد تفصیلی اپراتورها</h2><SkeletonTable columns={OPERATOR_COLUMNS} rows={Math.min(previous?.operators.length || 5, 25)} className="min-w-[780px]" /></section> : null}
      {!operator ? <section className="card overflow-x-auto"><h2 className="mb-4 font-bold">کمپین‌ها و منابع</h2><SkeletonTable columns={CAMPAIGN_COLUMNS} rows={Math.min(previous?.breakdowns.campaigns.length || 5, 25)} className="min-w-[600px]" /></section> : null}
      <section className="card overflow-x-auto"><div className="mb-3"><h2 className="font-bold">تماس‌های اخیر بازه</h2><p className="mt-1 text-sm text-slate-500">برای بررسی کامل، روی هر ردیف کلیک کنید.</p></div><SkeletonTable columns={RECENT_COLUMNS} rows={10} className="min-w-[780px]" /></section>
    </SkeletonRegion>
  );
}

export default function Overview() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();
  const operator = isOperator(session?.role);
  const orgAdmin = isOrgAdmin(session?.role);
  const range = searchParams.get("range") ?? "30";
  const fromInput = searchParams.get("from") ?? "";
  const toInput = searchParams.get("to") ?? "";
  const direction = searchParams.get("direction") ?? "";
  const campaign = searchParams.get("campaign") ?? "";
  const source = searchParams.get("source") ?? "";
  const intent = searchParams.get("intent") ?? "";
  const certainty = searchParams.get("certainty") ?? "";
  const team = searchParams.get("team") ?? "";
  const operatorId = searchParams.get("operator") ?? "";
  const operatorOffset = Math.max(0, Number(searchParams.get("operator_offset") ?? "0") || 0);
  const campaignOffset = Math.max(0, Number(searchParams.get("campaign_offset") ?? "0") || 0);
  const trendParam = searchParams.get("trend");
  const trendMetric: TrendMetric = TREND_METRICS.some((item) => item.value === trendParam) ? (trendParam as TrendMetric) : "calls";
  const funnelView: FunnelView = searchParams.get("funnel") === "sales" ? "sales" : "engagement";
  const attention = searchParams.get("attention") ?? "";
  const tableLimit = 25;
  const detailsOpen = searchParams.get("details") === "1";
  const incompleteRange = range === "custom" && (!fromInput || !toInput);
  const selectedRange = useMemo(() => rangeDates(range, fromInput, toInput), [range, fromInput, toInput]);
  const updateRange = (next: { range: string; from?: string; to?: string }) => {
    const params = new URLSearchParams(searchParams); params.set("range", next.range);
    if (next.range === "custom") { if (next.from) params.set("from", next.from); if (next.to) params.set("to", next.to); } else { params.delete("from"); params.delete("to"); }
    setSearchParams(params);
  };
  const clearAnalysisFilters = () => {
    const params = new URLSearchParams(searchParams);
    ["direction", "campaign", "source", "intent", "certainty", "team", "operator", "operator_offset", "campaign_offset"].forEach((key) => params.delete(key));
    setSearchParams(params);
  };
  const updateAnalysisFilter = (key: string, value: string, clearKey?: string) => {
    const params = new URLSearchParams(searchParams);
    if (value) params.set(key, value); else params.delete(key);
    if (clearKey) params.delete(clearKey);
    if (key !== "operator_offset" && key !== "campaign_offset") { params.delete("operator_offset"); params.delete("campaign_offset"); }
    setSearchParams(params);
  };
  /** View-only params (chart metric, expanded group) must not reset table pagination. */
  const updateViewParam = (key: string, value: string, fallback: string) => {
    const params = new URLSearchParams(searchParams);
    if (value && value !== fallback) params.set(key, value); else params.delete(key);
    setSearchParams(params, { replace: true });
  };
  const dashboard = useResource<{ data: KpiDashboard; recent: CallPage } | null>(async (signal) => {
    if (incompleteRange) return null;
    const filterQuery = { from: selectedRange.from, to: selectedRange.to, direction, campaign_id: campaign, source, intent, certainty, team_id: team, operator_id: operatorId };
    const [data, recent] = await Promise.all([
      request<KpiDashboard>(`/v1/kpi/dashboard${query({ ...filterQuery, operator_offset: operatorOffset, campaign_offset: campaignOffset, table_limit: tableLimit })}`, { signal }),
      request<CallPage>(`/v1/calls${query({ limit: 10, ...filterQuery })}`, { signal }),
    ]);
    return { data, recent };
  }, [campaign, campaignOffset, certainty, direction, fromInput, intent, operatorId, operatorOffset, range, selectedRange.from, selectedRange.to, source, team, toInput]);

  // The previous result stays available while a new one loads: filter options, widget set and row counts come from it.
  const previous = dashboard.data?.data;
  const live = dashboard.loading ? null : dashboard.data;
  const ctx: ViewContext = { operator, operatorOffset, campaignOffset, tableLimit, selectedRange, navigate, updateAnalysisFilter };
  const details = live ? detailView(live.data, live.recent, ctx) : null;
  const widgets = new Set(previous?.dashboard_widgets ?? DEFAULT_WIDGETS);
  const filters = previous?.filters ?? EMPTY_FILTERS;

  const strOptions = (items: string[], labels: Record<string, string> = {}) => items.map((item) => ({ value: item, label: labels[item] ?? item }));
  const analysisFilter = (id: string, label: string, value: string, options: { value: string; label: string }[], clearKey?: string): FilterBarField => ({
    id,
    label,
    active: Boolean(value),
    onRemove: () => updateAnalysisFilter(id, "", clearKey),
    control: <FilterSelect value={value} onChange={(next) => updateAnalysisFilter(id, next, clearKey)} options={options} />,
  });
  const analysisFilterFields: FilterBarField[] = [
    analysisFilter("direction", "جهت تماس", direction, strOptions(filters.directions, { inbound: "ورودی", outbound: "خروجی" })),
    analysisFilter("campaign", "کمپین", campaign, strOptions(filters.campaigns)),
    analysisFilter("source", "منبع", source, strOptions(filters.sources)),
    analysisFilter("intent", "قصد", intent, strOptions(filters.intents)),
    analysisFilter("certainty", "سطح اطمینان", certainty, strOptions(filters.certainties)),
    { ...analysisFilter("team", "تیم", team, filters.teams.map((item) => ({ value: item.id, label: item.name })), "operator"), hidden: operator },
    { ...analysisFilter("operator", "اپراتور", operatorId, filters.operators.map((item) => ({ value: item.id, label: item.name })), "team"), hidden: operator },
  ];

  const analysisFilterBar = useFilterBar({ fields: analysisFilterFields, hasActive: analysisFilterFields.some((field) => field.active), onClear: clearAnalysisFilters });
  const data = live?.data;
  const periodText = data ? `${fmt.date(data.from_date)} تا ${fmt.date(data.to_date)} · مقایسه با دورهٔ هم‌اندازهٔ قبل` : "مقایسه با دورهٔ هم‌اندازهٔ قبل";

  return <div className="dashboard-overview space-y-4" dir="rtl">
    <PageHeader title={operator ? "داشبورد عملکرد من" : "داشبورد سازمان"} description={periodText} actions={<div className="flex flex-wrap items-center justify-end gap-2">{analysisFilterBar.toolbar}<DateRangePicker range={range} from={fromInput} to={toInput} onChange={updateRange} compact /></div>} />
    {analysisFilterBar.fields ? <div className="card">{analysisFilterBar.fields}</div> : null}
    <ErrorBox message={dashboard.error} />
    {incompleteRange ? null : <>
      {operator ? <p className="border border-[color:var(--line)] bg-brand-50 px-4 py-3 text-sm text-brand-800">این داشبورد فقط داده‌های مجاز و منتسب به شما را نشان می‌دهد.</p> : null}
      {data ? <>
        <ExecutiveSummary data={data} operator={operator} />
        <KpiRow data={data} operator={operator} range={selectedRange} />
        <div className="exec-split">
          {widgets.has("actions") ? <AttentionPanel actions={data.actions} expanded={attention} onExpand={(type) => updateViewParam("attention", type, "")} range={selectedRange} /> : null}
          <GoalsPanel goals={data.cards.goal_achievement} canEdit={orgAdmin} />
        </div>
        {widgets.has("trend") ? <TrendPanel trend={data.trend} metric={trendMetric} onMetric={(value) => updateViewParam("trend", value, "calls")} /> : null}
        {widgets.has("funnel") ? <FunnelStrip views={data.funnel_views} view={funnelView} onView={(value) => updateViewParam("funnel", value, "engagement")} /> : null}
        <div className="exec-split exec-split--wide">
          {operator ? (widgets.has("coaching") ? <CoachingPanel coaching={data.coaching} /> : null) : widgets.has("operator_comparison") ? <TeamPanel operators={data.operators} total={data.operators_total} /> : null}
          {widgets.has("sentiment") ? <VoiceOfCustomer sentiments={data.sentiments} objections={data.breakdowns.objections} topics={data.breakdowns.topics} range={selectedRange} /> : null}
        </div>
      </> : <ExecutiveSkeleton operator={operator} />}
      <details className="card dashboard-details" open={detailsOpen} onToggle={(event) => { const next = event.currentTarget.open; if (next !== detailsOpen) updateViewParam("details", next ? "1" : "", ""); }}>
        <summary className="cursor-pointer font-bold">تحلیل‌های تکمیلی</summary>
        <p className="mt-1 text-sm text-slate-500">شاخص‌های CRM، کارها، تماس‌های بی‌پاسخ، تعادل گفت‌وگو، اعتراض‌ها و محصولات، جدول اپراتورها و کمپین‌ها و تماس‌های اخیر</p>
        {detailsOpen ? <div className="mt-5 space-y-4">
          {details ? <>
            {details.stats}
            <div className="exec-split">{details.tasks}{details.callTypes}</div>
            <div className="exec-split">{details.talkBalance}{details.coaching}</div>
            {details.voicemail}
            <DashboardCard title="اعتراض‌ها، محصولات و موضوعات" hint="در همان بازه و فیلترهای داشبورد">{details.breakdowns}</DashboardCard>
            {details.operatorsTable}{details.campaignsTable}{details.recent}
          </> : <DetailsSkeleton operator={operator} previous={previous} />}
        </div> : null}
      </details>
    </>}
  </div>;
}
