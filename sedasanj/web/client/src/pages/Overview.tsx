import { useMemo, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Icon } from "@iconify/react";
import checkMarkButtonIcon from "@iconify-icons/lucide/circle-check";
import chevronLeftIcon from "@iconify-icons/lucide/chevron-left";
import clockAlertIcon from "@iconify-icons/lucide/clock-alert";
import eyeIcon from "@iconify-icons/lucide/eye";
import flameIcon from "@iconify-icons/lucide/flame";
import trendingDownIcon from "@iconify-icons/lucide/trending-down";
import { chart } from "@cbi/web-shared/theme";
import { FilterSelect, useFilterBar, type FilterBarField } from "@cbi/web-shared/components/FilterBar";
import { DateRangePicker } from "../components/DateRangePicker";
import { PageHeader } from "../components/PageHeader";
import { EMPTY_STATE_ART } from "../components/pageArt";
import { TopicsCloud } from "../components/TopicsCloud";
import { fmt, query, request, SENTIMENT_LABELS } from "../api";
import { isOperator, useAuth } from "../auth";
import { Empty, ErrorBox, Pagination, SENTIMENT_EMOJI, SentimentBadge, Stat, StatusBadge, SummaryCell, TrajectoryBadge } from "../components/Widgets";
import type { CallPage, KpiDashboard, RateMetric } from "../types";
import { Skeleton, SkeletonChartCard, SkeletonBreakdown, SkeletonRegion, SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";

const SENTIMENT_COLORS: Record<string, string> = { angry: chart.danger, sad: chart.secondary, neutral: chart.warning, satisfied: chart.cyan, happy: chart.success };
const FUNNEL: Record<string, string> = { all_calls: "کل تماس‌ها", effective: "تماس مؤثر", qualified: "واجد شرایط", interested: "علاقه‌مند", follow_up: "پیگیری", proposal: "پیشنهاد", won: "فروش", lost: "ازدست‌رفته" };

function rangeDates(range: string, from: string, to: string) {
  if (range === "custom" && from && to) return { from: new Date(`${from}T00:00:00`).toISOString(), to: new Date(`${to}T23:59:59.999`).toISOString() };
  const end = new Date();
  return { from: new Date(end.getTime() - (Number(range) || 30) * 86400000).toISOString(), to: end.toISOString() };
}
function pct(metric: RateMetric) { return metric.value == null ? "—" : `${fmt.decimal(metric.value)}٪`; }
function delta(metric: RateMetric) { return metric.change == null ? "دورهٔ قبل داده کافی ندارد" : `${metric.change > 0 ? "+" : ""}${fmt.decimal(metric.change)} واحد نسبت به دورهٔ قبل`; }
function Widget({ enabled, children }: { enabled: boolean; children: ReactNode }) { return enabled ? <>{children}</> : null; }

function polar(angle: number, radius: number) {
  const rad = Math.PI - angle * Math.PI;
  return { x: 100 + radius * Math.cos(rad), y: 100 - radius * Math.sin(rad) };
}

/** Half-ring gauge on a 0-100 scale; null value renders an empty track. */
function Gauge({ title, value, hint, color }: { title: string; value: number | null; hint: string; color: string }) {
  const filled = value == null ? 0 : Math.min(100, Math.max(0, value));
  const ticks = Array.from({ length: 11 }, (_, index) => ({ inner: polar(index / 10, 66), outer: polar(index / 10, index % 5 === 0 ? 56 : 60) }));
  return <section className="card flex min-w-0 flex-col items-center text-center">
    <h2 className="self-start font-bold">{title}</h2>
    <svg className="mt-2 block h-auto w-full max-w-[17rem]" viewBox="0 0 200 118" role="img" aria-label={`${title}: ${value == null ? "نامشخص" : `${fmt.decimal(value)}٪`}`}>
      <path d="M20 100 A80 80 0 0 1 180 100" pathLength={100} fill="none" stroke="#e4e0d4" strokeWidth="16" />
      <path d="M20 100 A80 80 0 0 1 180 100" pathLength={100} fill="none" stroke={color} strokeWidth="16" strokeDasharray={`${filled} 100`} />
      {ticks.map((tick, index) => <line key={index} x1={tick.inner.x} y1={tick.inner.y} x2={tick.outer.x} y2={tick.outer.y} stroke="#898989" strokeWidth="1.5" />)}
      <text x="100" y="94" textAnchor="middle" className="fill-slate-800 text-[30px] font-black">{value == null ? "—" : `${fmt.decimal(value)}٪`}</text>
    </svg>
    <p className="mt-2 text-xs leading-5 text-slate-500">{hint}</p>
  </section>;
}

function DashboardEmpty({ title = "موردی یافت نشد.", description = "با ثبت داده‌های بیشتر، جزئیات این بخش نمایش داده می‌شود.", success = false }: { title?: string; description?: string; success?: boolean }) {
  const icon = success ? checkMarkButtonIcon : null;
  return <div className="panel-empty">{icon ? <span className="mb-3 flex h-14 w-14 items-center justify-center border border-current bg-emerald-50 text-emerald-700"><Icon icon={icon} className="h-7 w-7" /></span> : <img className="panel-empty__art" src={EMPTY_STATE_ART} alt="" aria-hidden="true" loading="lazy" decoding="async" />}<strong className={success ? "text-sm text-emerald-800" : "text-sm text-slate-700"}>{title}</strong><p className="mt-1 max-w-xs text-xs leading-6 text-slate-500">{description}</p></div>;
}

function ChartKey({ color, label }: { color: string; label: string }) {
  return <span className="inline-flex items-center gap-1.5 text-xs text-slate-600"><i className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} /><span>{label}</span></span>;
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
  return <div className="h-64 min-w-0 sm:h-72" dir="ltr"><ResponsiveContainer width="100%" height="100%"><BarChart data={rows} layout="vertical" margin={{ top: 8, right: 12, bottom: 4, left: 16 }}><CartesianGrid stroke={chart.light} strokeDasharray="3 5" horizontal={false} /><XAxis type="number" allowDecimals={false} tickFormatter={fmt.int} tick={{ fill: "#64748b", fontSize: 12 }} tickLine={false} axisLine={false} /><YAxis type="category" dataKey="label" width={110} tick={{ fill: "#64748b", fontSize: 12 }} tickLine={false} axisLine={false} /><Tooltip contentStyle={{ border: "1px solid #e2e8f0", borderRadius: 12, direction: "rtl", fontSize: 12 }} formatter={(value: number) => [fmt.int(value), "تماس"]} /><Bar dataKey="count" name="تماس" radius={[0, 8, 8, 0]}>{rows.map((item) => <Cell key={item.key} fill={CALL_TYPE_COLORS[item.key] ?? chart.danger} />)}</Bar></BarChart></ResponsiveContainer></div>;
}

function PerformanceTrendChart({ trend }: { trend: Array<KpiDashboard["trend"][number] & { label: string }> }) {
  return <div className="min-w-0 overflow-hidden"><div className="mb-4 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 sm:justify-start"><ChartKey color={chart.primary} label="کل تماس‌ها" /><ChartKey color={chart.secondary} label="تماس پاسخ‌داده‌شده" /><ChartKey color={chart.warning} label="فرصت فروش" /><ChartKey color={chart.success} label="فروش" /></div><div className="h-64 min-w-0 sm:h-72" dir="ltr"><ResponsiveContainer width="100%" height="100%"><LineChart data={trend} margin={{ top: 12, right: 10, bottom: 4, left: 10 }}><CartesianGrid stroke={chart.light} strokeDasharray="3 5" vertical={false} /><XAxis dataKey="label" interval="preserveStartEnd" minTickGap={38} tick={{ fill: "#64748b", fontSize: 12 }} tickLine={false} axisLine={false} tickMargin={12} /><YAxis orientation="right" width={42} allowDecimals={false} tickFormatter={fmt.int} tick={{ fill: "#64748b", fontSize: 12 }} tickLine={false} axisLine={false} /><Tooltip cursor={{ stroke: "#cbd5e1", strokeDasharray: "3 3" }} contentStyle={{ border: "1px solid #e2e8f0", borderRadius: 12, direction: "rtl", fontSize: 12 }} labelStyle={{ color: "#334155", marginBottom: 8 }} formatter={(value: number, name: string) => [fmt.int(value), name]} /><Line type="monotone" dataKey="calls" name="کل تماس‌ها" stroke={chart.primary} strokeWidth={2.5} dot={{ r: 2.5, strokeWidth: 2, fill: "#fff" }} activeDot={{ r: 5 }} /><Line type="monotone" dataKey="answered_calls" name="تماس پاسخ‌داده‌شده" stroke={chart.secondary} strokeWidth={2.5} dot={{ r: 2.5, strokeWidth: 2, fill: "#fff" }} activeDot={{ r: 5 }} /><Line type="monotone" dataKey="opportunities" name="فرصت فروش" stroke={chart.warning} strokeWidth={2.5} dot={{ r: 2.5, strokeWidth: 2, fill: "#fff" }} activeDot={{ r: 5 }} /><Line type="monotone" dataKey="wins" name="فروش" stroke={chart.success} strokeWidth={2.5} dot={{ r: 2.5, strokeWidth: 2, fill: "#fff" }} activeDot={{ r: 5 }} /></LineChart></ResponsiveContainer></div></div>;
}

const SENTIMENT_ORDER = ["happy", "satisfied", "neutral", "sad", "angry"] as const;
const SENTIMENT_TONES: Record<string, string> = { happy: "#176b34", satisfied: "#1c5aa3", neutral: "#4a5059", sad: "#b04a07", angry: "#b42318" };

/** Quick customer-satisfaction counts: all five sentiments, large emoji on top, call count below. */
function SentimentQuickStats({ sentiments }: { sentiments: Array<{ key: string; count: number }> }) {
  const counts = new Map(sentiments.map((item) => [item.key, item.count]));
  const total = SENTIMENT_ORDER.reduce((sum, key) => sum + (counts.get(key) ?? 0), 0);
  return <section className="card">
    <h2 className="font-bold">رضایت مشتری در یک نگاه</h2>
    <p className="section-hint mb-4">تعداد تماس‌های تحلیل‌شدهٔ بازه به تفکیک احساس مشتری</p>
    <div className="grid grid-cols-5 gap-2 sm:gap-4">
      {SENTIMENT_ORDER.map((key) => {
        const count = counts.get(key) ?? 0;
        return <div key={key} className="flex min-w-0 flex-col items-center gap-1 px-1 py-4 text-center">
          <span className="text-4xl leading-none sm:text-6xl" role="img" aria-label={SENTIMENT_LABELS[key]}>{SENTIMENT_EMOJI[key]}</span>
          <strong className="mt-2 text-xl font-extrabold tabular-nums sm:text-3xl" style={{ color: SENTIMENT_TONES[key] }}>{fmt.int(count)}</strong>
          <span className="truncate text-[11px] sm:text-sm">{SENTIMENT_LABELS[key]}</span>
          <span className="text-[11px] text-slate-500 sm:text-xs">{total ? fmt.decimal(count * 100 / total) : fmt.decimal(0)}٪</span>
        </div>;
      })}
    </div>
  </section>;
}

function SentimentCharts({ sentiments }: { sentiments: Array<KpiDashboard["sentiments"][number] & { label: string }> }) {
  const total = sentiments.reduce((sum, item) => sum + item.count, 0);
  const details = sentiments.map((item) => ({ ...item, percent: total ? item.count * 100 / total : 0 }));
  return <div className="grid min-w-0 gap-6 lg:grid-cols-2"><div className="relative h-64 min-w-0 overflow-hidden sm:h-72"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={details} dataKey="count" nameKey="label" innerRadius="58%" outerRadius="78%" paddingAngle={3} stroke="#F2F0EF" strokeWidth={2}>{details.map((item) => <Cell key={item.key} fill={SENTIMENT_COLORS[item.key] ?? chart.primary} />)}</Pie><Tooltip contentStyle={{ border: "1px solid #e2e8f0", borderRadius: 12, direction: "rtl", fontSize: 12 }} formatter={(value: number) => fmt.int(value)} /></PieChart></ResponsiveContainer><div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"><span className="text-2xl font-black text-slate-800">{fmt.int(total)}</span><span className="mt-1 text-xs text-slate-500">تحلیل احساس</span></div></div><div className="min-w-0"><div className="space-y-4">{details.map((item) => <div key={item.key}><div className="mb-2 flex items-center justify-between gap-4"><ChartKey color={SENTIMENT_COLORS[item.key] ?? chart.primary} label={item.label} /><div className="flex shrink-0 items-center gap-2 text-xs"><strong className="text-slate-700">{fmt.int(item.count)} تماس</strong><span className="text-slate-500">{fmt.decimal(item.percent)}٪</span></div></div><div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full" style={{ width: `${item.percent}%`, backgroundColor: SENTIMENT_COLORS[item.key] ?? chart.primary }} /></div></div>)}</div></div></div>;
}

type FunnelRow = { key: string; label: string; count: number; pass_rate: number | null; drop_rate: number | null };
const FUNNEL_COLORS = ["#3f5f3d", "#4b6e48", "#5f805b", "#789074", "#8fa68a", "#b2ac88"];
const FUNNEL_TEXT_ON_LIGHT = new Set(["#8fa68a", "#b2ac88"]);

function funnelColor(index: number, total: number) {
  return FUNNEL_COLORS[total > 1 ? Math.round(index * (FUNNEL_COLORS.length - 1) / (total - 1)) : 0];
}

function SalesFunnel({ rows }: { rows: FunnelRow[] }) {
  const rim = 14;
  const stageHeight = 62;
  const gap = 3;
  const maxWidth = 540;
  const minWidth = 170;
  const center = 300;
  const neckHeight = 44;
  const first = Math.max(rows[0]?.count ?? 0, 1);
  const widths: number[] = [];
  rows.forEach((row, index) => {
    const proportional = rows[0] && rows[0].count > 0 ? minWidth + (maxWidth - minWidth) * (row.count / first) : maxWidth - (maxWidth - minWidth) * (index / Math.max(rows.length, 1));
    widths.push(index === 0 ? maxWidth : Math.min(proportional, widths[index - 1] - 24));
  });
  const lastWidth = widths[widths.length - 1] ?? minWidth;
  const neckWidth = Math.max(lastWidth * 0.34, 56);
  const stagesEnd = rim + rows.length * (stageHeight + gap) - gap;
  const height = stagesEnd + neckHeight + 6;
  return <div className="mx-auto w-full max-w-md py-2"><svg className="block h-auto w-full" viewBox={`0 0 600 ${height}`} role="img" aria-label="قیف مراحل">
    <defs><linearGradient id="funnel-sheen" x1="0" x2="1"><stop offset="0" stopColor="#fff" stopOpacity="0.18" /><stop offset="0.45" stopColor="#fff" stopOpacity="0" /><stop offset="1" stopColor="#000" stopOpacity="0.1" /></linearGradient></defs>
    <ellipse cx={center} cy={rim} rx={widths[0] / 2} ry={rim} fill="#e4e0d4" stroke="#3f5f3d" strokeWidth="2" />
    {rows.map((row, index) => {
      const y = rim + index * (stageHeight + gap);
      const topHalf = widths[index] / 2;
      const bottomHalf = (index < rows.length - 1 ? widths[index + 1] : neckWidth * 1.6) / 2;
      const color = funnelColor(index, rows.length);
      const textClass = FUNNEL_TEXT_ON_LIGHT.has(color) ? "fill-[#20251f]" : "fill-[#f2f0ef]";
      return <g key={row.key}><title>{`${row.label}: ${fmt.int(row.count)}`}</title><polygon points={`${center - topHalf},${y} ${center + topHalf},${y} ${center + bottomHalf},${y + stageHeight} ${center - bottomHalf},${y + stageHeight}`} fill={color} /><polygon points={`${center - topHalf},${y} ${center + topHalf},${y} ${center + bottomHalf},${y + stageHeight} ${center - bottomHalf},${y + stageHeight}`} fill="url(#funnel-sheen)" /><text x={center} y={y + 27} textAnchor="middle" className={`${textClass} text-[20px] font-black`}>{fmt.int(row.count)}</text><text x={center} y={y + 47} textAnchor="middle" direction="rtl" className={`${textClass} text-[13px] font-bold`}>{row.label}</text></g>;
    })}
    <polygon points={`${center - neckWidth * 0.8},${stagesEnd + gap} ${center + neckWidth * 0.8},${stagesEnd + gap} ${center + neckWidth / 2},${height - 6} ${center - neckWidth / 2},${height - 6}`} fill="#b2ac88" />
  </svg></div>;
}

function FunnelPanel({ title, description, rows }: { title: string; description: string; rows: FunnelRow[] }) {
  return <section className="card"><h2 className="font-bold">{title}</h2><p className="mb-4 mt-1 text-sm text-slate-500">{description}</p>{rows.length ? <div className="grid items-center gap-5 lg:grid-cols-[minmax(0,1fr)_12rem]"><SalesFunnel rows={rows} /><ol className="funnel-steps">{rows.map((row, index) => <li key={row.key}><i style={{ background: funnelColor(index, rows.length) }} aria-hidden="true" /><div className="min-w-0 flex-1"><div className="flex items-baseline justify-between gap-2"><strong className="truncate text-sm">{row.label}</strong><span className="shrink-0 text-sm font-bold tabular-nums text-[#4b6e48]">{fmt.int(row.count)}</span></div><p className="mt-0.5 text-[11px] text-slate-500">عبور {row.pass_rate == null ? "—" : `${fmt.decimal(row.pass_rate)}٪`} · ریزش {row.drop_rate == null ? "—" : `${fmt.decimal(row.drop_rate)}٪`}</p></div></li>)}</ol></div> : <Empty />}</section>;
}

function Breakdown({ title, rows }: { title: string; rows: Array<[string, number]> }) {
  const max = Math.max(1, ...rows.map((row) => row[1]));
  return <section className="min-w-0 bg-[#F2F0EF] p-5"><h3 className="mb-4 text-sm font-bold text-slate-800">{title}</h3>{rows.length ? <div className="space-y-3">{rows.map(([label, count]) => <div key={label}><div className="mb-1 flex items-center justify-between gap-3 text-xs"><span className="truncate text-slate-700">{label}</span><strong className="shrink-0 text-slate-600">{fmt.int(count)}</strong></div><div className="h-1.5 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500" style={{ width: `${count * 100 / max}%` }} /></div></div>)}</div> : <DashboardEmpty title="داده کافی وجود ندارد." description="پس از تکمیل تحلیل تماس‌ها، این بخش نمایش داده می‌شود." />}</section>;
}

const ACTION_META: Record<string, { label: string; icon: typeof flameIcon }> = {
  hot_opportunity: { label: "فرصت داغ بدون پیگیری", icon: flameIcon },
  overdue_follow_up: { label: "پیگیری عقب‌افتاده", icon: clockAlertIcon },
  kpi_decline: { label: "افت شاخص عملکرد", icon: trendingDownIcon },
};
const REVIEW_ACTION = { label: "نیازمند بازبینی", icon: eyeIcon };

/** One action: severity bar, type icon, label, description (two lines reserved so cards align). */
function ActionCard({ action }: { action: KpiDashboard["actions"][number] }) {
  const meta = ACTION_META[action.type] ?? REVIEW_ACTION;
  const urgent = action.severity === "high";
  const tone = urgent ? chart.danger : chart.warning;
  const content = (
    <>
      <span className="flex h-9 w-9 shrink-0 items-center justify-center border border-[color:var(--line)] bg-[#F2F0EF]" style={{ color: tone }} aria-hidden="true"><Icon icon={meta.icon} className="h-5 w-5" /></span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <strong className="truncate text-sm text-slate-800">{meta.label}</strong>
          <span className="shrink-0 border px-2 text-xs leading-5" style={{ borderColor: tone, color: tone }}>{urgent ? "فوری" : "بازبینی"}</span>
        </div>
        <p className="mt-1 line-clamp-2 min-h-10 text-sm leading-5 text-slate-500">{action.title}</p>
      </div>
      {action.call_id ? <Icon icon={chevronLeftIcon} className="mt-2 h-4 w-4 shrink-0 text-[#898989] transition group-hover:-translate-x-0.5 group-hover:text-[#4B6E48]" aria-hidden="true" /> : null}
    </>
  );
  const className = "group flex items-start gap-3 border border-[color:var(--line)] bg-[#F2F0EF] p-4";
  const style = { borderInlineStartWidth: 3, borderInlineStartColor: tone };
  return action.call_id
    ? <Link to={`/calls/${action.call_id}`} className={`${className} transition hover:bg-white`} style={style}>{content}</Link>
    : <div className={className} style={style}>{content}</div>;
}

function ActionCenter({ actions }: { actions: KpiDashboard["actions"] }) {
  const urgent = actions.filter((item) => item.severity === "high").length;
  return <section className="card">
    <div className="mb-4 flex items-center justify-between gap-3">
      <div><h2 className="font-bold">مرکز اقدام</h2><p className="mt-1 text-sm text-slate-500">موارد نیازمند پیگیری یا بازبینی</p></div>
      <div className="flex shrink-0 items-center gap-2 text-xs">
        {urgent ? <span className="border px-2 py-1 font-bold" style={{ borderColor: chart.danger, color: chart.danger }}>{fmt.int(urgent)} فوری</span> : null}
        <span className="border border-[#4B6E48] px-2 py-1 font-bold text-[#4B6E48]">{fmt.int(actions.length)} مورد</span>
      </div>
    </div>
    {actions.length ? <div className="grid gap-3 md:grid-cols-2">{actions.slice(0, 8).map((item, index) => <ActionCard key={`${item.call_id ?? item.type}-${index}`} action={item} />)}</div> : <DashboardEmpty success title="اقدام فوری باقی نمانده است." description="همهٔ پیگیری‌های ضروری این بازه مدیریت شده‌اند." />}
  </section>;
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

/** Every data-dependent section of the dashboard, built from one loaded payload. */
function dashboardView(data: KpiDashboard, recent: CallPage, ctx: ViewContext) {
  const { operator, operatorOffset, campaignOffset, tableLimit, selectedRange, navigate, updateAnalysisFilter } = ctx;
  const c = data.cards;
  const widgets = new Set(data.dashboard_widgets);
  const trend = data.trend.map((item) => ({ ...item, label: fmt.calendarDate(item.date) }));
  const engagementFunnel = data.funnel_views.engagement.map((item) => ({ ...item, label: item.key === "opportunities" ? "فرصت فروش" : FUNNEL[item.key] ?? item.key }));
  const salesFunnel = data.funnel_views.sales.map((item) => ({ ...item, label: FUNNEL[item.key] ?? item.key }));
  const sentiments = data.sentiments.map((item) => ({ ...item, label: SENTIMENT_LABELS[item.key] ?? item.key }));
  const talk = [{ name: "اپراتور", value: c.talk_balance.agent_percent ?? 0, color: chart.primary }, { name: "مشتری", value: c.talk_balance.caller_percent ?? 0, color: chart.cyan }];
  return {
    gauges: <div className="grid gap-4 md:grid-cols-3"><Gauge title={operator ? "نرخ تبدیل من" : "نرخ تبدیل"} value={c.ai_win_rate.value} hint={delta(c.ai_win_rate)} color={chart.success} /><Gauge title="میانگین کیفیت" value={c.quality_score} hint={c.quality_score == null ? "نمونهٔ امتیازدهی کافی نیست" : "از تماس‌های امتیازدهی‌شده"} color={chart.primary} /><Gauge title="پیگیری در SLA" value={c.follow_up_sla_rate.value} hint={delta(c.follow_up_sla_rate)} color={chart.cyan} /></div>,
    stats: <div className="grid gap-3 sm:grid-cols-2 sm:[&>:last-child:nth-child(odd)]:col-span-2 lg:grid-cols-3 lg:[&>:last-child:nth-child(odd)]:col-span-1"><Stat title="تماس مؤثر" value={fmt.int(c.effective_calls)} hint={`${fmt.int(c.total_calls)} کل تماس · ${fmt.int(c.missed_calls)} بی‌پاسخ`} /><Stat title="فرصت فروش" value={fmt.int(c.opportunities)} hint={`${fmt.int(c.probable_opportunities)} فرصت محتمل`} /><Stat title={operator ? "نرخ تبدیل من" : "نرخ تبدیل AI"} value={pct(c.ai_win_rate)} hint={delta(c.ai_win_rate)} /><Stat title="میانگین کیفیت" value={c.quality_score == null ? "—" : fmt.decimal(c.quality_score)} hint={c.quality_score == null ? "نمونهٔ امتیازدهی کافی نیست" : "از تماس‌های امتیازدهی‌شده"} /><Stat title="پیام صوتی" value={fmt.int(c.voicemail_calls)} hint={`${fmt.duration(c.voicemail_total_duration_ms)} مدت کل · ${fmt.decimal(c.voicemail_transcription_rate)}٪ رونویسی‌شده`} />{!operator ? <><Stat title="تبدیل رسمی CRM" value={pct(c.crm_conversion_rate)} hint={delta(c.crm_conversion_rate)} /><Stat title="ارزش فروش" value={c.currency ? `${fmt.int(c.revenue)} ${c.currency}` : "—"} hint={c.currency ? `پایپ‌لاین: ${fmt.int(c.pipeline_value)} ${c.currency}` : "دادهٔ CRM کافی نیست"} /></> : null}<Stat title="پیگیری در SLA" value={pct(c.follow_up_sla_rate)} hint={delta(c.follow_up_sla_rate)} /><Link to="/tasks" className="block transition hover:opacity-90"><Stat title="اقدام فوری" value={fmt.int(c.hot_unassigned)} hint="فرصت داغ بدون پیگیری" tone={c.hot_unassigned ? "text-rose-700" : undefined} /></Link></div>,
    emojis: <Widget enabled={widgets.has("sentiment")}><SentimentQuickStats sentiments={data.sentiments} /></Widget>,
    trend: <Widget enabled={widgets.has("trend")}><section className="card"><h2 className="font-bold">روند عملکرد روزانه</h2><p className="mb-4 mt-1 text-sm text-slate-500">کل تماس‌ها، تماس‌های پاسخ‌داده‌شده، فرصت فروش و فروش در بازهٔ انتخابی</p>{trend.length ? <PerformanceTrendChart trend={trend} /> : <Empty />}</section></Widget>,
    voicemail: !operator ? <section className="card"><h2 className="font-bold">تفکیک پیام‌های صوتی بر اساس داخلی صندوق</h2><p className="mb-4 mt-1 text-sm text-slate-500">مدت میانگین هر پیام: {fmt.duration(c.voicemail_average_duration_ms)} · پیام‌های دارای متن: {fmt.int(c.voicemail_transcribed_calls)}</p>{data.voicemail_mailboxes.length ? <div className="flex flex-wrap gap-2">{data.voicemail_mailboxes.map((item) => <span key={item.mailbox} className="border border-[color:var(--line)] bg-[#F2F0EF] px-3 py-2 text-sm">داخلی {fmt.digits(item.mailbox)} <strong className="ms-2">{fmt.int(item.count)}</strong></span>)}</div> : <Empty />}</section> : null,
    callTypes: <Widget enabled={widgets.has("trend")}><section className="card"><h2 className="font-bold">توزیع نوع تماس‌های بی‌پاسخ</h2><p className="mb-4 mt-1 text-sm text-slate-500">تفکیک تماس‌های بدون پاسخ، مشغول، اختلال مسیر و سایر خطاهای نهایی</p><CallTypeChart items={data.call_types} /></section></Widget>,
    engagementFunnel: <Widget enabled={widgets.has("funnel")}><FunnelPanel title="قیف تماس تا فرصت" description="از تمام تماس‌ها تا فرصت‌های واقعی و فروش صریح؛ هر مرحله زیرمجموعهٔ مرحلهٔ قبل است." rows={engagementFunnel} /></Widget>,
    salesFunnel: <Widget enabled={widgets.has("funnel")}><FunnelPanel title="قیف پیشروی فروش" description="فقط فرصت‌های واجد شرایط در مسیر فروش؛ باخت‌ها عمداً خارج از قیف نگه داشته می‌شوند." rows={salesFunnel} /></Widget>,
    sentiment: <Widget enabled={widgets.has("sentiment")}><section className="card"><h2 className="font-bold">احساس مشتری</h2><p className="mb-4 mt-1 text-sm text-slate-500">توزیع، سهم و تعداد تحلیل‌های تکمیل‌شده در بازه</p>{sentiments.length ? <SentimentCharts sentiments={sentiments} /> : <Empty />}</section></Widget>,
    operatorsChart: <Widget enabled={widgets.has("operator_comparison")}><section className="card"><h2 className="font-bold">{operator ? "عملکرد من" : "مقایسهٔ اپراتورها"}</h2><p className="mb-4 mt-1 text-sm text-slate-500">نرخ تبدیل و کیفیت فقط با نمونهٔ کافی قابل اتکاست.</p>{data.operators.length ? <div className="h-80"><ResponsiveContainer><BarChart data={data.operators} layout="vertical" margin={{ right: 20, left: 24 }}><CartesianGrid stroke={chart.light} strokeDasharray="3 3" /><XAxis type="number" domain={[0, 100]} tickFormatter={(value) => fmt.percent(value)} /><YAxis type="category" dataKey="operator_label" width={92} /><Tooltip formatter={(value: number) => `${fmt.decimal(value)}٪`} /><Legend /><Bar dataKey={(item) => item.conversion.value ?? 0} name="تبدیل" fill={chart.success} radius={[0, 8, 8, 0]} /><Bar dataKey={(item) => item.quality_score ?? 0} name="کیفیت" fill={chart.primary} radius={[0, 8, 8, 0]} /></BarChart></ResponsiveContainer></div> : <Empty />}</section></Widget>,
    talkBalance: <Widget enabled={widgets.has("talk_balance")}><section className="card"><h2 className="font-bold">تعادل گفت‌وگو</h2><p className="mb-4 mt-1 text-sm text-slate-500">سهم زمانی صحبت اپراتور و مشتری</p>{c.talk_balance.agent_percent == null ? <Empty /> : <div className="grid items-center gap-4 sm:grid-cols-2"><div className="h-64"><ResponsiveContainer><PieChart><Pie data={talk} dataKey="value" nameKey="name" innerRadius={52} outerRadius={88} paddingAngle={3}>{talk.map((item) => <Cell key={item.name} fill={item.color} />)}</Pie><Tooltip formatter={(value: number) => `${fmt.decimal(value)}٪`} /><Legend /></PieChart></ResponsiveContainer></div><div className="space-y-3">{talk.map((item) => <div key={item.name} className="rounded-xl bg-slate-50 p-4"><p className="text-sm text-slate-500">{item.name}</p><strong className="mt-1 block text-2xl">{fmt.decimal(item.value)}٪</strong></div>)}</div></div>}</section></Widget>,
    tasks: <Widget enabled={widgets.has("tasks")}><section className="card"><div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold">وضعیت کارهای قابل پیگیری</h2><p className="mt-1 text-sm text-slate-500">میزان انجام‌شدن و وضعیت کارهای منتسب به تماس‌های این بازه</p></div><Link to="/tasks" className="btn-ghost inline-flex h-9 items-center px-3 py-0 text-xs">مشاهدهٔ همه کارها</Link></div><div className="grid items-center gap-5"><div className="h-64"><ResponsiveContainer><BarChart data={[{ name: "انجام‌شده", value: c.task_summary.done, fill: chart.success }, { name: "باز", value: c.task_summary.open, fill: chart.warning }, { name: "عقب‌افتاده", value: c.task_summary.overdue, fill: chart.danger }]}><CartesianGrid stroke={chart.light} strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis orientation="right" allowDecimals={false} tickFormatter={fmt.int} /><Tooltip formatter={(value: number) => fmt.int(value)} /><Bar dataKey="value" name="تعداد" radius={[8, 8, 0, 0]}>{[chart.success, chart.warning, chart.danger].map((fill) => <Cell key={fill} fill={fill} />)}</Bar></BarChart></ResponsiveContainer></div><div className="space-y-3"><div className="rounded-2xl bg-emerald-50 p-4"><p className="text-sm text-emerald-800">نرخ تکمیل</p><strong className="mt-1 block text-3xl text-emerald-800">{pct(c.task_summary.completion_rate)}</strong><p className="mt-1 text-xs text-emerald-700">{delta(c.task_summary.completion_rate)}</p></div><div className="grid grid-cols-3 gap-2 text-center text-xs"><div className="rounded-xl bg-slate-50 p-3"><strong className="block text-lg">{fmt.int(c.task_summary.done)}</strong><span className="text-slate-500">انجام‌شده</span></div><div className="rounded-xl bg-amber-50 p-3"><strong className="block text-lg">{fmt.int(c.task_summary.open)}</strong><span className="text-amber-800">باز</span></div><div className="rounded-xl bg-rose-50 p-3"><strong className="block text-lg">{fmt.int(c.task_summary.overdue)}</strong><span className="text-rose-800">عقب‌افتاده</span></div></div></div></div></section></Widget>,
    coaching: <Widget enabled={widgets.has("coaching")}><div className="grid gap-4 xl:grid-cols-2"><section className="card"><h2 className="mb-4 font-bold text-emerald-700">نقاط قوت</h2><Coaching rows={data.coaching.strengths} tone="emerald" /></section><section className="card"><h2 className="mb-4 font-bold text-amber-700">اولویت‌های بهبود</h2><Coaching rows={data.coaching.improvements} tone="amber" /></section></div></Widget>,
    operatorsTable: !operator ? <section className="card overflow-x-auto"><h2 className="mb-4 font-bold">عملکرد تفصیلی اپراتورها</h2><table className="table min-w-[780px]"><thead><tr><th>اپراتور</th><th>تماس پاسخ‌داده‌شده</th><th>تماس بی‌پاسخ</th><th>فرصت</th><th>فروش</th><th>تبدیل</th><th>کیفیت</th><th>سهم صحبت</th><th>نمونه</th></tr></thead><tbody>{data.operators.map((item) => <tr key={item.operator_id}><td>{item.operator_label}</td><td>{fmt.int(item.calls)}</td><td>{fmt.int(item.missed_calls)}</td><td>{fmt.int(item.opportunities)}</td><td>{fmt.int(item.wins)}</td><td>{pct(item.conversion)}</td><td>{item.quality_score == null ? "—" : fmt.decimal(item.quality_score)}</td><td>{item.agent_talk_ratio == null ? "—" : `${fmt.decimal(item.agent_talk_ratio)}٪`}</td><td className={item.sample_sufficient ? "text-emerald-700" : "text-amber-700"}>{item.sample_sufficient ? "کافی" : "ناکافی"}</td></tr>)}</tbody></table><Pagination page={Math.floor(operatorOffset / tableLimit) + 1} hasPrevious={operatorOffset > 0} hasNext={operatorOffset + tableLimit < data.operators_total} total={data.operators_total} onPrevious={() => updateAnalysisFilter("operator_offset", String(Math.max(0, operatorOffset - tableLimit)))} onNext={() => updateAnalysisFilter("operator_offset", String(operatorOffset + tableLimit))} /></section> : null,
    campaignsTable: !operator ? <section className="card overflow-x-auto"><h2 className="mb-4 font-bold">کمپین‌ها و منابع</h2><table className="table min-w-[600px]"><thead><tr><th>کمپین / منبع</th><th>تماس</th><th>فرصت</th><th>فروش</th><th>نرخ برد AI</th></tr></thead><tbody>{data.breakdowns.campaigns.map((item) => <tr key={item.key}><td>{item.key === "unknown" ? "منبع نامشخص" : item.key}</td><td>{fmt.int(item.calls)}</td><td>{fmt.int(item.opportunities)}</td><td>{fmt.int(item.wins)}</td><td>{pct(item.conversion)}</td></tr>)}</tbody></table><Pagination page={Math.floor(campaignOffset / tableLimit) + 1} hasPrevious={campaignOffset > 0} hasNext={campaignOffset + tableLimit < data.breakdowns.campaigns_total} total={data.breakdowns.campaigns_total} onPrevious={() => updateAnalysisFilter("campaign_offset", String(Math.max(0, campaignOffset - tableLimit)))} onNext={() => updateAnalysisFilter("campaign_offset", String(campaignOffset + tableLimit))} /></section> : null,
    actions: <Widget enabled={widgets.has("actions")}><ActionCenter actions={data.actions} /></Widget>,
    recent: <section className="card overflow-x-auto"><div className="mb-3 flex items-center justify-between"><div><h2 className="font-bold">تماس‌های اخیر بازه</h2><p className="mt-1 text-sm text-slate-500">برای بررسی کامل، روی هر ردیف کلیک کنید.</p></div><Link to={`/calls${query({ from: selectedRange.from, to: selectedRange.to })}`} className="btn-ghost inline-flex h-9 items-center px-3 py-0 text-xs">همه تماس‌ها</Link></div>{recent.items.length ? <table className="table min-w-[780px]"><thead><tr><th>زمان</th><th>شماره</th><th>مدت</th><th>خلاصه</th><th>وضعیت</th><th>احساس</th><th>تغییر</th></tr></thead><tbody>{recent.items.map((call) => <tr key={call.id} className="table-row-link" role="link" tabIndex={0} onClick={() => navigate(`/calls/${call.id}`)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); navigate(`/calls/${call.id}`); } }}><td>{fmt.dateTime(call.started_at)}</td><td dir="ltr">{call.caller_number ? fmt.digits(call.caller_number) : "—"}</td><td>{fmt.duration(call.duration_ms)}</td><SummaryCell summary={call.summary} /><td><StatusBadge status={call.call_type === "answered" ? call.status : call.call_type} /></td><td><SentimentBadge sentiment={call.sentiment} /></td><td><TrajectoryBadge trajectory={call.sentiment_trajectory} /></td></tr>)}</tbody></table> : <Empty />}</section>,
    breakdowns: <div className="mt-5 grid gap-px overflow-hidden border border-[color:var(--line)] bg-[#B2AC88] lg:grid-cols-2"><Breakdown title="اعتراض‌های پرتکرار" rows={data.breakdowns.objections} /><Breakdown title="محصولات و خدمات" rows={data.breakdowns.products} /><TopicsCloud rows={data.breakdowns.topics} emptyState={<DashboardEmpty title="داده کافی وجود ندارد." description="پس از تکمیل تحلیل تماس‌ها، این بخش نمایش داده می‌شود." />} /><Breakdown title="دلایل برد و باخت" rows={data.breakdowns.win_loss_reasons} /></div>,
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

/** Placeholder for the headline charts; titles and descriptions are the real, static text. */
function OverviewSkeleton({ operator, widgets }: { operator: boolean; widgets: Set<string> }) {
  return (
    <SkeletonRegion>
      <div className="grid gap-4 md:grid-cols-3">
        {["نرخ تبدیل", "میانگین کیفیت", "پیگیری در SLA"].map((title) => <section key={title} className="card" aria-hidden="true"><h2 className="font-bold">{title}</h2><Skeleton className="mx-auto mt-2 w-full max-w-[17rem]" style={{ aspectRatio: "200 / 118" }} /></section>)}
      </div>
      <Widget enabled={widgets.has("trend")}><SkeletonChartCard title="روند عملکرد روزانه" description="کل تماس‌ها، تماس‌های پاسخ‌داده‌شده، فرصت فروش و فروش در بازهٔ انتخابی" legend /></Widget>
      <div className="grid gap-4 xl:grid-cols-2">
        <Widget enabled={widgets.has("funnel")}><SkeletonChartCard title="قیف تماس تا فرصت" description="از تمام تماس‌ها تا فرصت‌های واقعی و فروش صریح؛ هر مرحله زیرمجموعهٔ مرحلهٔ قبل است." heightClassName="h-80" /></Widget>
        <Widget enabled={widgets.has("operator_comparison")}><SkeletonChartCard title={operator ? "عملکرد من" : "مقایسهٔ اپراتورها"} description="نرخ تبدیل و کیفیت فقط با نمونهٔ کافی قابل اتکاست." heightClassName="h-80" /></Widget>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Widget enabled={widgets.has("tasks")}><SkeletonChartCard title="وضعیت کارهای قابل پیگیری" description="میزان انجام‌شدن و وضعیت کارهای منتسب به تماس‌های این بازه" heightClassName="h-64" /></Widget>
        <Widget enabled={widgets.has("trend")}><SkeletonChartCard title="توزیع نوع تماس‌های بی‌پاسخ" description="تفکیک تماس‌های بدون پاسخ، مشغول، اختلال مسیر و سایر خطاهای نهایی" /></Widget>
      </div>
    </SkeletonRegion>
  );
}

function TablesSkeleton({ operator, widgets, previous }: { operator: boolean; widgets: Set<string>; previous: KpiDashboard | undefined }) {
  return (
    <SkeletonRegion>
      {!operator ? <section className="card overflow-x-auto"><h2 className="mb-4 font-bold">عملکرد تفصیلی اپراتورها</h2><SkeletonTable columns={OPERATOR_COLUMNS} rows={Math.min(previous?.operators.length || 5, 25)} className="min-w-[780px]" /></section> : null}
      {!operator ? <section className="card overflow-x-auto"><h2 className="mb-4 font-bold">کمپین‌ها و منابع</h2><SkeletonTable columns={CAMPAIGN_COLUMNS} rows={Math.min(previous?.breakdowns.campaigns.length || 5, 25)} className="min-w-[600px]" /></section> : null}
      <Widget enabled={widgets.has("actions")}>
        <section className="card" aria-hidden="true">
          <div className="mb-4 flex items-center justify-between"><div><h2 className="font-bold">مرکز اقدام</h2><p className="mt-1 text-sm text-slate-500">موارد نیازمند پیگیری یا بازبینی</p></div><Skeleton style={{ width: "4.5rem", height: "1.75rem" }} /></div>
          <div className="grid gap-3 md:grid-cols-2">{Array.from({ length: previous ? Math.min(previous.actions.length, 8) || 1 : 4 }, (_, index) => <Skeleton key={index} className="w-full" style={{ height: "6.25rem" }} />)}</div>
        </section>
      </Widget>
      <section className="card overflow-x-auto"><div className="mb-3 flex items-center justify-between"><div><h2 className="font-bold">تماس‌های اخیر بازه</h2><p className="mt-1 text-sm text-slate-500">برای بررسی کامل، روی هر ردیف کلیک کنید.</p></div></div><SkeletonTable columns={RECENT_COLUMNS} rows={10} className="min-w-[780px]" /></section>
    </SkeletonRegion>
  );
}

export default function Overview() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { session } = useAuth();
  const operator = isOperator(session?.role);
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
  const view = live ? dashboardView(live.data, live.recent, { operator, operatorOffset, campaignOffset, tableLimit, selectedRange, navigate, updateAnalysisFilter }) : null;
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

  return <div className="dashboard-overview space-y-5" dir="rtl">
    <PageHeader title={operator ? "داشبورد عملکرد من" : "داشبورد هوشمند سازمان"} description={operator ? "تصمیم‌های روزانه و روند عملکرد شخصی شما" : "فروش و کیفیت مکالمه در یک نمای تصمیم‌ساز"} actions={<DateRangePicker range={range} from={fromInput} to={toInput} onChange={updateRange} compact />} />
    <ErrorBox message={dashboard.error} />
    {incompleteRange ? null : <>
      {operator ? <p className="rounded-xl border border-brand-100 bg-brand-50 px-4 py-3 text-sm text-brand-800">این داشبورد فقط داده‌های مجاز و منتسب به شما را نشان می‌دهد.</p> : null}
      {view ? <>{view.emojis}{view.gauges}{view.trend}<div className="grid gap-4 xl:grid-cols-2">{view.engagementFunnel}{view.operatorsChart}</div><div className="grid gap-4 xl:grid-cols-2">{view.tasks}{view.callTypes}</div></> : <OverviewSkeleton operator={operator} widgets={widgets} />}
      <details className="card dashboard-details" open={detailsOpen} onToggle={(event) => { const next = event.currentTarget.open; if (next !== detailsOpen) updateAnalysisFilter("details", next ? "1" : ""); }}>
        <summary className="cursor-pointer font-bold">جزئیات بیشتر</summary>
        <p className="mt-1 text-sm text-slate-500">شاخص‌های عددی، قیف فروش، تحلیل احساس، مربی‌گری، جدول‌ها و تماس‌های اخیر</p>
        {detailsOpen ? <div className="mt-5 space-y-5">
          {view ? <>{view.stats}{view.voicemail}{view.salesFunnel}{view.sentiment}{view.talkBalance}{view.coaching}</> : null}
          <section className="card"><div className="mb-4 flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-bold">تحلیل‌های تکمیلی</h2><p className="mt-1 text-sm text-slate-500">موضوع‌ها، اعتراض‌ها، محصول‌ها و عملکرد تفصیلی در همان بازهٔ داشبورد</p></div>{analysisFilterBar.toolbar}</div>{analysisFilterBar.fields ? <div className="mb-5">{analysisFilterBar.fields}</div> : null}{view ? view.breakdowns : <SkeletonRegion><div className="mt-5 grid gap-px overflow-hidden border border-[color:var(--line)] bg-[#B2AC88] lg:grid-cols-2"><SkeletonBreakdown title="اعتراض‌های پرتکرار" rows={previous?.breakdowns.objections.length || 5} /><SkeletonBreakdown title="محصولات و خدمات" rows={previous?.breakdowns.products.length || 5} /><section className="min-w-0 bg-[#F2F0EF] p-5" aria-hidden="true"><h3 className="mb-4 text-sm font-bold text-slate-800">موضوعات پرتکرار</h3><Skeleton className="min-h-44 w-full" /></section><SkeletonBreakdown title="دلایل برد و باخت" rows={previous?.breakdowns.win_loss_reasons.length || 5} /></div></SkeletonRegion>}</section>
          {view ? <>{view.operatorsTable}{view.campaignsTable}{view.actions}{view.recent}</> : <TablesSkeleton operator={operator} widgets={widgets} previous={previous} />}
        </div> : null}
      </details>
    </>}
  </div>;
}

function Coaching({ rows, tone }: { rows: KpiDashboard["coaching"]["strengths"]; tone: "emerald" | "amber" }) { if (!rows.length) return <Empty />; return <div className="space-y-3">{rows.map((item) => <Link key={`${item.call_id}-${item.title}`} to={`/calls/${item.call_id}`} className={`block rounded-xl p-4 ${tone === "emerald" ? "bg-emerald-50" : "bg-amber-50"}`}><div className="flex justify-between gap-4"><strong>{item.title}</strong><span>{fmt.decimal(item.average)}</span></div>{item.evidence ? <p className="mt-2 text-xs text-slate-600">{item.evidence}</p> : null}</Link>)}</div>; }
