import type { ReactNode } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Funnel, FunnelChart, LabelList, Legend, Line, LineChart, Pie, PieChart, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, RadialBar, RadialBarChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, Treemap, XAxis, YAxis } from "recharts";
import { fmt, STATUS_LABELS } from "../api";
import type { AssistantChart } from "../types";

const assistantChartColors = ["#4B6E48", "#B2AC88", "#7A8B73", "#898989", "#D8D3B9"];

export function AssistantCharts({ charts, print = false }: { charts: AssistantChart[]; print?: boolean }) {
  const animate = print ? false : undefined;
  const axisPadding = print ? { left: 36, right: 30 } : undefined;
  const visible = charts.filter((chart) => chart.data.some((item) => Number.isFinite(item.value)));
  if (!visible.length) return null;
  return <section className="statistics-charts mt-4 grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="نمودارهای آماری">
    {visible.map((chart) => {
      const data = chart.data.map((item, index) => ({
        ...item,
        label: STATUS_LABELS[item.label] || (/^\d{4}-\d{2}-\d{2}$/.test(item.label) ? fmt.calendarDate(item.label) : item.label),
        fill: assistantChartColors[index % assistantChartColors.length],
        x: index + 1,
        y: item.value,
        z: item.secondary_value || 1,
      }));
      const tooltip = <Tooltip formatter={(value, name) => [fmt.decimal(Number(value)), name === "secondary_value" ? chart.secondary_value_label || "مقدار دوم" : chart.value_label]} />;
      let visualization: ReactNode;
      if (chart.type === "pie" || chart.type === "donut") visualization = <PieChart><Pie isAnimationActive={animate} data={data} dataKey="value" nameKey="label" innerRadius={chart.type === "donut" ? 54 : 0} outerRadius={82} paddingAngle={2}>{data.map((item) => <Cell key={`${chart.id}-${item.label}`} fill={item.fill} />)}</Pie>{tooltip}<Legend wrapperStyle={{ direction: "rtl", fontSize: 11 }} /></PieChart>;
      else if (chart.type === "line") visualization = <LineChart data={data}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis dataKey="label" padding={axisPadding} tick={{ fontSize: 10 }} /><YAxis orientation="right" tickFormatter={(value) => fmt.int(Number(value))} /><Line isAnimationActive={animate} type="monotone" dataKey="value" name={chart.value_label} stroke="#4B6E48" strokeWidth={2} />{tooltip}</LineChart>;
      else if (chart.type === "area") visualization = <AreaChart data={data}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis dataKey="label" padding={axisPadding} tick={{ fontSize: 10 }} /><YAxis orientation="right" tickFormatter={(value) => fmt.int(Number(value))} /><Area isAnimationActive={animate} type="monotone" dataKey="value" name={chart.value_label} stroke="#4B6E48" fill="#B2AC88" fillOpacity={0.55} />{tooltip}</AreaChart>;
      else if (chart.type === "radar") visualization = <RadarChart data={data}><PolarGrid stroke="#D8D3B9" /><PolarAngleAxis dataKey="label" tick={{ fontSize: 10 }} /><PolarRadiusAxis tickFormatter={(value) => fmt.int(Number(value))} /><Radar isAnimationActive={animate} dataKey="value" name={chart.value_label} stroke="#4B6E48" fill="#4B6E48" fillOpacity={0.35} />{tooltip}<Legend /></RadarChart>;
      else if (chart.type === "radial_bar") visualization = <RadialBarChart data={data} innerRadius="18%" outerRadius="92%" startAngle={90} endAngle={-270}><RadialBar isAnimationActive={animate} dataKey="value" name={chart.value_label} background label={{ position: "insideStart", fill: "#fff", fontSize: 10 }} />{tooltip}<Legend iconSize={10} layout="vertical" verticalAlign="middle" align="right" /></RadialBarChart>;
      else if (chart.type === "scatter") visualization = <ScatterChart><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis type="number" dataKey="x" name="ردیف" allowDecimals={false} /><YAxis type="number" dataKey="y" name={chart.value_label} orientation="right" /><Scatter isAnimationActive={animate} data={data} name={chart.value_label} fill="#4B6E48" />{tooltip}</ScatterChart>;
      else if (chart.type === "composed") visualization = <ComposedChart data={data}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis dataKey="label" padding={axisPadding} tick={{ fontSize: 10 }} /><YAxis orientation="right" /><Bar isAnimationActive={animate} dataKey="value" name={chart.value_label} fill="#B2AC88" /><Line isAnimationActive={animate} type="monotone" dataKey="secondary_value" name={chart.secondary_value_label || "مقدار دوم"} stroke="#4B6E48" strokeWidth={2} />{tooltip}<Legend /></ComposedChart>;
      else if (chart.type === "treemap") visualization = <Treemap isAnimationActive={animate} data={data} dataKey="value" nameKey="label" stroke="#F2F0EF" fill="#4B6E48">{tooltip}</Treemap>;
      else if (chart.type === "funnel") visualization = <FunnelChart><Tooltip formatter={(value) => [fmt.decimal(Number(value)), chart.value_label]} /><Funnel isAnimationActive={animate} dataKey="value" data={data}><LabelList position="right" fill="#4B6E48" stroke="none" dataKey="label" /></Funnel></FunnelChart>;
      else if (chart.type === "horizontal_bar") visualization = <BarChart data={data} layout="vertical" margin={{ right: 16, left: 24 }}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis type="number" tickFormatter={(value) => fmt.int(Number(value))} /><YAxis type="category" dataKey="label" width={84} tick={{ fontSize: 10 }} /><Bar isAnimationActive={animate} dataKey="value" name={chart.value_label} fill="#4B6E48" />{tooltip}</BarChart>;
      else visualization = <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 32 }}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis dataKey="label" interval={0} angle={-18} textAnchor="end" height={58} tick={{ fontSize: 10 }} /><YAxis orientation="right" allowDecimals={false} tickFormatter={(value) => fmt.int(Number(value))} />{tooltip}<Bar isAnimationActive={animate} dataKey="value" name={chart.value_label} fill="#4B6E48" /></BarChart>;
      return <article key={chart.id} className={`statistics-chart min-w-0 border border-[#B2AC88] bg-white p-3 ${chart.size === "full" ? "md:col-span-2" : ""}`}>
        <h3 className="mb-3 text-sm font-bold text-[#4B6E48]">{chart.title}</h3>
        <div className="h-64 w-full" dir="ltr">
          <ResponsiveContainer width="100%" height="100%">{visualization}</ResponsiveContainer>
        </div>
      </article>;
    })}
  </section>;
}
