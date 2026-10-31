import { Area, Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt } from "../../api";
import type { KpiDashboard } from "../../types";
import { Empty } from "../Widgets";
import { DashboardCard, Segmented } from "./DashboardCard";

export type TrendMetric = "calls" | "sales" | "quality" | "satisfaction";

export const TREND_METRICS: Array<{ value: TrendMetric; label: string }> = [
  { value: "calls", label: "تماس" },
  { value: "sales", label: "فرصت و فروش" },
  { value: "quality", label: "کیفیت" },
  { value: "satisfaction", label: "رضایت" },
];

const HINTS: Record<TrendMetric, string> = {
  calls: "کل تماس‌ها و تماس‌های پاسخ‌داده‌شده در هر روز",
  sales: "فرصت‌های فروش و فروش‌های قطعی در هر روز",
  quality: "میانگین امتیاز کیفیت مکالمه‌های امتیازدهی‌شده در هر روز",
  satisfaction: "سهم مشتریان راضی و خوشحال از تماس‌های تحلیل‌شدهٔ هر روز",
};

const AXIS = { fill: "#6f716b", fontSize: 12 };
const TOOLTIP = { border: "1px solid #b2ac88", borderRadius: 0, background: "#f2f0ef", direction: "rtl" as const, fontSize: 12 };

function Key({ color, label, bar = false }: { color: string; label: string; bar?: boolean }) {
  return <span className="inline-flex items-center gap-1.5 text-xs text-slate-600"><i className={bar ? "h-2.5 w-2.5" : "h-0.5 w-4"} style={{ background: color }} aria-hidden="true" />{label}</span>;
}

/** One trend chart with a metric switch; the chosen metric lives in the URL. */
export function TrendPanel({ trend, metric, onMetric }: { trend: KpiDashboard["trend"]; metric: TrendMetric; onMetric: (value: TrendMetric) => void }) {
  const rows = trend.map((item) => ({
    ...item,
    label: fmt.calendarDate(item.date),
    satisfaction: item.sentiment_known ? Math.round((item.positive_sentiments * 1000) / item.sentiment_known) / 10 : null,
  }));
  const percent = metric === "satisfaction";
  const keys = {
    calls: [<Key key="c" color="#b2ac88" label="کل تماس‌ها" bar />, <Key key="a" color="#4b6e48" label="پاسخ‌داده‌شده" />],
    sales: [<Key key="o" color="#b2ac88" label="فرصت فروش" bar />, <Key key="w" color="#4b6e48" label="فروش" />],
    quality: [<Key key="q" color="#4b6e48" label="میانگین کیفیت" />],
    satisfaction: [<Key key="s" color="#4b6e48" label="سهم مشتریان راضی" />],
  }[metric];
  return <DashboardCard title="روند روزانه" hint={HINTS[metric]} action={<Segmented label="شاخص نمودار روند" value={metric} options={TREND_METRICS} onChange={onMetric} />}>
    {rows.length ? <>
      <div className="mb-3 flex flex-wrap gap-x-5 gap-y-2">{keys}</div>
      <div className="h-64 min-w-0 sm:h-72" dir="ltr">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
            <CartesianGrid stroke="#d8d4c2" strokeDasharray="3 5" vertical={false} />
            <XAxis dataKey="label" interval="preserveStartEnd" minTickGap={40} tick={AXIS} tickLine={false} axisLine={false} tickMargin={10} />
            <YAxis orientation="right" width={44} allowDecimals={false} domain={metric === "quality" || percent ? [0, 100] : [0, "auto"]} tickFormatter={(value: number) => (percent ? `${fmt.int(value)}٪` : fmt.int(value))} tick={AXIS} tickLine={false} axisLine={false} />
            <Tooltip cursor={{ stroke: "#898989", strokeDasharray: "3 3" }} contentStyle={TOOLTIP} labelStyle={{ color: "#23281f", marginBottom: 6 }} formatter={(value: number, name: string) => [percent ? `${fmt.decimal(value)}٪` : fmt.decimal(value), name]} />
            {metric === "calls" ? [
              <Area key="calls" type="monotone" dataKey="calls" name="کل تماس‌ها" stroke="#b2ac88" fill="#b2ac88" fillOpacity={0.22} strokeWidth={1.5} />,
              <Line key="answered" type="monotone" dataKey="answered_calls" name="پاسخ‌داده‌شده" stroke="#4b6e48" strokeWidth={2.2} dot={false} activeDot={{ r: 4 }} />,
            ] : null}
            {metric === "sales" ? [
              <Bar key="opportunities" dataKey="opportunities" name="فرصت فروش" fill="#b2ac88" maxBarSize={18} />,
              <Line key="wins" type="monotone" dataKey="wins" name="فروش" stroke="#4b6e48" strokeWidth={2.2} dot={{ r: 2.5, fill: "#4b6e48" }} activeDot={{ r: 4 }} />,
            ] : null}
            {metric === "quality" ? <Line type="monotone" dataKey="quality_score" name="میانگین کیفیت" stroke="#4b6e48" strokeWidth={2.2} connectNulls dot={{ r: 2.5, fill: "#4b6e48" }} activeDot={{ r: 4 }} /> : null}
            {metric === "satisfaction" ? <Line type="monotone" dataKey="satisfaction" name="سهم مشتریان راضی" stroke="#4b6e48" strokeWidth={2.2} connectNulls dot={{ r: 2.5, fill: "#4b6e48" }} activeDot={{ r: 4 }} /> : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </> : <Empty />}
  </DashboardCard>;
}
