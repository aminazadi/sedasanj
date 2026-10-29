import AssistantContextPicker, { AssistantAttachmentChips } from "../components/AssistantContextPicker";
import AssistantExportFiles from "../components/AssistantExportFiles";
import { CallStateArt } from "../components/CallStateArt";
import { FormEvent, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { io, type Socket } from "socket.io-client";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Funnel, FunnelChart, LabelList, Legend, Line, LineChart, Pie, PieChart, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart, RadialBar, RadialBarChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, Treemap, XAxis, YAxis } from "recharts";
import { fmt, INTENT_LABELS, refreshSession, request, STATUS_LABELS, tokens } from "../api";
import { isOrgAdmin, useAuth } from "../auth";
import ConversationBubble from "../components/ConversationBubble";
import ConfirmDialog from "../components/ConfirmDialog";
import MarkdownMessage from "../components/MarkdownMessage";
import PersianSpeechInputButton from "../components/PersianSpeechInputButton";
import { ErrorBox, SentimentBadge, StatusBadge } from "../components/Widgets";
import { Skeleton } from "@cbi/web-shared/components/Skeleton";
import { useDesktopMenuToggle } from "../components/Layout";
import type { AssistantCallSource, AssistantChart, AssistantContextOptions, AssistantMessageAttachments, AssistantToolRun, ChatConversation, ChatMessage, OrganizationMemory } from "../types";
import { downloadTextFile, safeDownloadName } from "../utils/download";
import { isFreshRunSequence, mergeSnapshotMessages, orderUniqueRunEvents, reconcileAcceptedMessage, withConversationRunState } from "./assistantRunState.mjs";

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="h-4 w-4">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v5M14 11v5" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="h-4 w-4">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

function ArchiveIcon({ restore = false }: { restore?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
      <path d="M4 7h16v13H4Z" />
      <path d="M3 3h18v4H3Z" />
      <path d="M9 11h6" />
      {restore ? <path d="m9 16-3-3 3-3M6 13h6" /> : null}
    </svg>
  );
}

function PinIcon({ pinned = false }: { pinned?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
      <path d="M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6Z" fill={pinned ? "currentColor" : "none"} />
      <path d="M12 14v7" />
    </svg>
  );
}

function TemporaryChatIcon({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
      <path d="M20 15a3 3 0 0 1-3 3H9l-5 3v-6a3 3 0 0 1-1-2.24V7a3 3 0 0 1 3-3h7" />
      <circle cx="17" cy="7" r="4" />
      <path d="M17 5v2.25l1.5 1" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-5 w-5">
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 21h14" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="h-5 w-5">
      <path d="m22 2-7 20-4-9-9-4Z" />
      <path d="M22 2 11 13" />
    </svg>
  );
}

function StopIcon() {
  return <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="h-4 w-4"><rect x="5" y="5" width="14" height="14" rx="1" /></svg>;
}

function CalendarIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-3.5 w-3.5"><path d="M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z" /></svg>;
}

function ToolsIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-3.5 w-3.5"><path d="m14.7 6.3 3-3a4 4 0 0 1-5 5l-7.4 7.4a2 2 0 1 0 3 3l7.4-7.4a4 4 0 0 1 5-5l-3 3" /><path d="m5 5 4 4" /></svg>;
}

function CloseIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" aria-hidden="true" className="h-4 w-4 shrink-0"><path d="m6 6 12 12M18 6 6 18" /></svg>;
}

function InfoIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4"><circle cx="12" cy="12" r="9" /><path d="M12 10v6m0-9h.01" /></svg>;
}

function FilterIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4"><path d="M3 5h18l-7 8v5l-4 2v-7Z" /></svg>;
}

function ScrollDownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-5 w-5">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function RetryIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
      <path d="M20 7v5h-5" />
      <path d="M19 12a7 7 0 1 0-2 5" />
    </svg>
  );
}

function CopyIcon({ checked = false }: { checked?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
      {checked ? <path d="m5 12 4 4L19 6" /> : <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" /></>}
    </svg>
  );
}

function ChatIcon({ active, className = "h-5 w-5" }: { active: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`${className} shrink-0 ${active ? "text-[#4B6E48]" : "text-[#898989] transition group-hover:text-[#4B6E48]"}`}>
      <path d="M12 2v4M8 3h8M5 8h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2ZM9 13h.01M15 13h.01M9 17h6" />
    </svg>
  );
}

function ConversationProcessingIndicator({ active }: { active: boolean }) {
  return <span className={`assistant-conversation-processing ${active ? "is-active" : ""}`} role="status" aria-label="در حال پردازش پاسخ دستیار"><span /><span /><span /><span /></span>;
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="h-5 w-5">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function MenuIcon({ close = false }: { close?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="h-5 w-5">
      {close ? <><path d="m18 6-12 12" /><path d="m6 6 12 12" /></> : <><path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h16" /></>}
    </svg>
  );
}

function IconTooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 hidden w-max -translate-x-1/2 border border-[#B2AC88] bg-[#4B6E48] px-2.5 py-1.5 text-[11px] font-medium text-[#F2F0EF] shadow-lg group-hover:block group-focus-within:block" role="tooltip">
        {label}
      </span>
    </span>
  );
}

function assistantErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message.trim() : "";
  if (/^internal server error$/i.test(message)) return "خطای داخلی سرور";
  return message || "خطایی در دستیار رخ داد.";
}

export function TypingIndicator({ label = "در حال فکر کردن و دریافت نتیجه ..." }: { label?: string }) {
  return (
    <div className="flex h-8 items-center gap-2" role="status" aria-live="polite">
      <ConversationProcessingIndicator active />
      <span className="assistant-thinking-text">{label}</span>
    </div>
  );
}

export function ToolTimeline({ runs, active }: { runs: AssistantToolRun[]; active: boolean }) {
  const [open, setOpen] = useState(active);
  useEffect(() => { if (active) setOpen(true); }, [active]);
  if (!runs.length) return null;
  const succeeded = runs.filter((run) => run.status === "succeeded").length;
  return <div className="mb-3 border border-[#B2AC88] bg-white/70 text-xs text-[#4B6E48]" aria-live="polite">
    <button type="button" className="flex w-full items-center justify-between gap-3 px-3 py-2 text-right font-bold" onClick={() => setOpen((current) => !current)} aria-expanded={open}>
      <span>{active ? "در حال استفاده از ابزارها" : `${fmt.int(succeeded)} ابزار استفاده شد`}</span>
      <span aria-hidden="true">{open ? "−" : "+"}</span>
    </button>
    {open ? <ol className="space-y-2 border-t border-[#B2AC88] px-3 py-2">
      {runs.map((run) => <li key={run.tool_call_id} className="flex items-start gap-2">
        <span className={`mt-0.5 inline-block h-2.5 w-2.5 shrink-0 ${run.status === "running" ? "animate-pulse bg-[#B2AC88]" : run.status === "succeeded" ? "bg-[#4B6E48]" : "bg-rose-600"}`} />
        <span className="min-w-0"><span className="font-bold">{run.title}</span>{run.summary ? <span className="mr-2 text-[#898989]">{run.summary}</span> : run.status === "failed" ? <span className="mr-2 text-rose-700">اجرای ابزار ناموفق بود</span> : <span className="mr-2 text-[#898989]">در حال اجرا…</span>}</span>
      </li>)}
    </ol> : null}
  </div>;
}

const assistantChartColors = ["#4B6E48", "#B2AC88", "#7A8B73", "#898989", "#D8D3B9"];

export function AssistantCharts({ charts }: { charts: AssistantChart[] }) {
  const visible = charts.filter((chart) => chart.data.some((item) => Number.isFinite(item.value)));
  if (!visible.length) return null;
  return <section className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="نمودارهای آماری پاسخ">
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
      if (chart.type === "pie" || chart.type === "donut") visualization = <PieChart><Pie data={data} dataKey="value" nameKey="label" innerRadius={chart.type === "donut" ? 54 : 0} outerRadius={82} paddingAngle={2}>{data.map((item) => <Cell key={`${chart.id}-${item.label}`} fill={item.fill} />)}</Pie>{tooltip}<Legend wrapperStyle={{ direction: "rtl", fontSize: 11 }} /></PieChart>;
      else if (chart.type === "line") visualization = <LineChart data={data}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis dataKey="label" tick={{ fontSize: 10 }} /><YAxis orientation="right" tickFormatter={(value) => fmt.int(Number(value))} /><Line type="monotone" dataKey="value" name={chart.value_label} stroke="#4B6E48" strokeWidth={2} />{tooltip}</LineChart>;
      else if (chart.type === "area") visualization = <AreaChart data={data}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis dataKey="label" tick={{ fontSize: 10 }} /><YAxis orientation="right" tickFormatter={(value) => fmt.int(Number(value))} /><Area type="monotone" dataKey="value" name={chart.value_label} stroke="#4B6E48" fill="#B2AC88" fillOpacity={0.55} />{tooltip}</AreaChart>;
      else if (chart.type === "radar") visualization = <RadarChart data={data}><PolarGrid stroke="#D8D3B9" /><PolarAngleAxis dataKey="label" tick={{ fontSize: 10 }} /><PolarRadiusAxis tickFormatter={(value) => fmt.int(Number(value))} /><Radar dataKey="value" name={chart.value_label} stroke="#4B6E48" fill="#4B6E48" fillOpacity={0.35} />{tooltip}<Legend /></RadarChart>;
      else if (chart.type === "radial_bar") visualization = <RadialBarChart data={data} innerRadius="18%" outerRadius="92%" startAngle={90} endAngle={-270}><RadialBar dataKey="value" name={chart.value_label} background label={{ position: "insideStart", fill: "#fff", fontSize: 10 }} />{tooltip}<Legend iconSize={10} layout="vertical" verticalAlign="middle" align="right" /></RadialBarChart>;
      else if (chart.type === "scatter") visualization = <ScatterChart><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis type="number" dataKey="x" name="ردیف" allowDecimals={false} /><YAxis type="number" dataKey="y" name={chart.value_label} orientation="right" /><Scatter data={data} name={chart.value_label} fill="#4B6E48" />{tooltip}</ScatterChart>;
      else if (chart.type === "composed") visualization = <ComposedChart data={data}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis dataKey="label" tick={{ fontSize: 10 }} /><YAxis orientation="right" /><Bar dataKey="value" name={chart.value_label} fill="#B2AC88" /><Line type="monotone" dataKey="secondary_value" name={chart.secondary_value_label || "مقدار دوم"} stroke="#4B6E48" strokeWidth={2} />{tooltip}<Legend /></ComposedChart>;
      else if (chart.type === "treemap") visualization = <Treemap data={data} dataKey="value" nameKey="label" stroke="#F2F0EF" fill="#4B6E48">{tooltip}</Treemap>;
      else if (chart.type === "funnel") visualization = <FunnelChart><Tooltip formatter={(value) => [fmt.decimal(Number(value)), chart.value_label]} /><Funnel dataKey="value" data={data} isAnimationActive><LabelList position="right" fill="#4B6E48" stroke="none" dataKey="label" /></Funnel></FunnelChart>;
      else if (chart.type === "horizontal_bar") visualization = <BarChart data={data} layout="vertical" margin={{ right: 16, left: 24 }}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis type="number" tickFormatter={(value) => fmt.int(Number(value))} /><YAxis type="category" dataKey="label" width={84} tick={{ fontSize: 10 }} /><Bar dataKey="value" name={chart.value_label} fill="#4B6E48" />{tooltip}</BarChart>;
      else visualization = <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 32 }}><CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" /><XAxis dataKey="label" interval={0} angle={-18} textAnchor="end" height={58} tick={{ fontSize: 10 }} /><YAxis orientation="right" allowDecimals={false} tickFormatter={(value) => fmt.int(Number(value))} />{tooltip}<Bar dataKey="value" name={chart.value_label} fill="#4B6E48" /></BarChart>;
      return <article key={chart.id} className={`min-w-0 border border-[#B2AC88] bg-white p-3 ${chart.size === "full" ? "md:col-span-2" : ""}`}>
      <h3 className="mb-3 text-sm font-bold text-[#4B6E48]">{chart.title}</h3>
      <div className="h-64 w-full" dir="ltr">
        <ResponsiveContainer width="100%" height="100%">{visualization}</ResponsiveContainer>
      </div>
    </article>;
    })}
  </section>;
}

function PhoneIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-5 w-5"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.33 1.78.62 2.63a2 2 0 0 1-.45 2.11L8 9.73a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.85.29 1.73.5 2.63.62A2 2 0 0 1 22 16.92Z" /></svg>;
}

function ChevronIcon({ open }: { open: boolean }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}><path d="m6 9 6 6 6-6" /></svg>;
}

export function CallSources({ sources, expandedCallId, onToggle }: { sources: AssistantCallSource[]; expandedCallId: string | null; onToggle: (callId: string) => void }) {
  return <section className="mt-4 border-t border-[#B2AC88] pt-3" aria-label="تماس‌های استفاده‌شده در پاسخ">
    <div className="mb-3 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 text-[#4B6E48]"><PhoneIcon /><h3 className="text-sm font-bold">تماس‌های بررسی‌شده</h3></div>
      <span className="border border-[#B2AC88] bg-[#F2F0EF] px-2 py-1 text-[11px] font-bold text-[#4B6E48]">{fmt.int(sources.length)} تماس</span>
    </div>
    <div className="max-h-[30rem] overflow-auto border border-[#B2AC88] bg-white">
      <table className="w-full min-w-[48rem] table-fixed border-collapse text-[11px]">
        <thead className="sticky top-0 z-10 bg-[#F2F0EF] text-[#4B6E48]">
          <tr className="border-b border-[#B2AC88]">
            <th className="w-9 p-0" aria-label="نمایش جزئیات" />
            <th className="w-36 px-2 py-2 text-center">تاریخ و زمان</th>
            <th className="w-56 px-2 py-2 text-center">طرفین تماس</th>
            <th className="w-16 px-2 py-2 text-center">اپراتور</th>
            <th className="w-14 px-2 py-2 text-center">جهت</th>
            <th className="w-14 px-2 py-2 text-center">مدت</th>
            <th className="w-20 px-2 py-2 text-center">وضعیت</th>
          </tr>
        </thead>
        {sources.map((source) => {
          const open = expandedCallId === source.call_id;
          const callerNumber = source.caller_number ? fmt.digits(source.caller_number) : "شماره نامشخص";
          const dialedNumber = source.dialed_number ? fmt.digits(source.dialed_number) : "شماره نامشخص";
          const detailsId = `assistant-call-source-${source.call_id}`;
          return <tbody key={source.call_id} className="border-b border-[#E3E0D4] last:border-b-0">
            <tr className={`transition hover:bg-[#F2F0EF] ${open ? "bg-[#F2F0EF]" : "bg-white"}`}>
              <td className="p-0">
                <button type="button" className="flex h-9 w-full items-center justify-center text-[#4B6E48]" onClick={() => onToggle(source.call_id)} aria-expanded={open} aria-controls={detailsId} aria-label={open ? "بستن جزئیات تماس" : "نمایش جزئیات تماس"}><ChevronIcon open={open} /></button>
              </td>
              <td className="whitespace-nowrap px-2 py-1.5 text-center text-[#555555]">{source.started_at ? fmt.dateTime(source.started_at) : "زمان نامشخص"}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-center font-bold text-[#4B6E48]" dir="ltr"><span>{callerNumber}</span><span className="px-1.5 text-[#898989]" dir="rtl">←</span><span>{dialedNumber}</span></td>
              <td className="whitespace-nowrap px-2 py-1.5 text-center" dir="ltr">{source.agent_extension ? fmt.digits(source.agent_extension) : "—"}</td>
              <td className="px-2 py-1.5 text-center">{source.direction === "inbound" ? "ورودی" : source.direction === "outbound" ? "خروجی" : source.direction || "—"}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-center">{source.duration_ms == null ? "—" : fmt.duration(source.duration_ms)}</td>
              <td className="px-2 py-1.5 text-center">{source.status ? <StatusBadge status={source.status} /> : "—"}</td>
            </tr>
            {open ? <tr id={detailsId}>
              <td colSpan={7} className="bg-[#FCFBF8] px-4 py-4">
                <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto]">
                  <div className="min-w-0">
                    <dl className="mb-3 grid grid-cols-2 gap-3 text-[11px] sm:grid-cols-3">
                      <div><dt className="text-[#898989]">شماره تماس‌گیرنده</dt><dd className="mt-1 font-bold" dir="ltr">{callerNumber}</dd></div>
                      <div><dt className="text-[#898989]">شماره مقصد</dt><dd className="mt-1 font-bold" dir="ltr">{dialedNumber}</dd></div>
                      <div><dt className="text-[#898989]">داخلی اپراتور</dt><dd className="mt-1 font-bold" dir="ltr">{source.agent_extension ? fmt.digits(source.agent_extension) : "—"}</dd></div>
                    </dl>
                    <div className="mb-3 flex flex-wrap items-center gap-2">
                      {source.intent ? <span className="border border-[#D8D3B9] bg-[#F2F0EF] px-2 py-1 text-[11px] text-[#4B6E48]">{INTENT_LABELS[source.intent] ?? source.intent}</span> : null}
                      {source.sentiment ? <SentimentBadge sentiment={source.sentiment} /> : null}
                    </div>
                    <p className="text-xs leading-6 text-[#555555]">{source.summary || "خلاصه‌ای برای این تماس ثبت نشده است."}</p>
                  </div>
                  <Link className="inline-flex h-10 items-center justify-center self-end border border-[#4B6E48] px-4 text-xs font-bold text-[#4B6E48] transition hover:bg-[#4B6E48] hover:text-white" to={`/calls/${source.call_id}`}>مشاهده تماس</Link>
                </div>
              </td>
            </tr> : null}
          </tbody>;
        })}
      </table>
    </div>
  </section>;
}

const promptGuides = [
  "برای ارسال، Ctrl + Enter را بزنید",
  "هوش مصنوعی می‌تواند خطا کند",
  "برای جست‌وجو و انتخاب اپراتور یا گفتگوی قبلی، @ را تایپ کنید",
  "بازه زمانی و ابزارهای موردنیاز را از دکمه‌های روبه‌رو انتخاب کنید",
];

const emptyAttachments = (): AssistantMessageAttachments => ({
  operator_id: null,
  conversation_ids: [],
  from_date: null,
  to_date: null,
  tool_names: [],
});

function TypingPromptGuide() {
  const [guideIndex, setGuideIndex] = useState(0);
  const [characterCount, setCharacterCount] = useState(0);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const guide = promptGuides[guideIndex];
    const finishedTyping = characterCount === Array.from(guide).length;
    const finishedDeleting = characterCount === 0;
    const delay = finishedTyping ? 2200 : deleting ? 24 : 48;
    const timer = window.setTimeout(() => {
      if (finishedTyping && !deleting) {
        setDeleting(true);
        return;
      }
      if (deleting && finishedDeleting) {
        setDeleting(false);
        setGuideIndex((current) => (current + 1) % promptGuides.length);
        return;
      }
      setCharacterCount((current) => current + (deleting ? -1 : 1));
    }, delay);
    return () => window.clearTimeout(timer);
  }, [characterCount, deleting, guideIndex]);

  return <span aria-hidden="true">{Array.from(promptGuides[guideIndex]).slice(0, characterCount).join("")}<span className="animate-pulse">|</span></span>;
}

function AssistantBubbleSkeleton({ side, lines }: { side: "user" | "assistant"; lines: number[] }) {
  return (
    <div className="flex w-full items-end gap-4" dir="ltr" style={{ justifyContent: side === "user" ? "flex-end" : "flex-start" }}>
      {side === "assistant" ? <Skeleton style={{ width: "2.25rem", height: "2.25rem" }} /> : null}
      <div className="flex max-w-[calc(85%_-_2.75rem)] w-full flex-col gap-2 border border-[#B2AC88] bg-white px-4 py-3 sm:w-[28rem]" dir="rtl">
        {lines.map((width, index) => <Skeleton key={index} className="skeleton--line" style={{ width: `${width}%` }} />)}
      </div>
      {side === "user" ? <Skeleton style={{ width: "2.25rem", height: "2.25rem" }} /> : null}
    </div>
  );
}

/** Placeholder for the message area only, shown while another conversation loads. */
function AssistantMessagesSkeleton() {
  return (
    <div className="space-y-5" aria-hidden="true">
      <span className="sr-only" role="status">در حال بارگذاری</span>
      <AssistantBubbleSkeleton side="user" lines={[70]} />
      <AssistantBubbleSkeleton side="assistant" lines={[95, 88, 60]} />
      <AssistantBubbleSkeleton side="user" lines={[55]} />
      <AssistantBubbleSkeleton side="assistant" lines={[92, 75]} />
    </div>
  );
}

/** Placeholder for the conversation list only, shown while another tab's list loads. */
function AssistantListSkeleton({ label = "گفتگوهای فعال" }: { label?: string }) {
  return (
    <div className="mb-5" aria-hidden="true">
      <span className="sr-only" role="status">در حال بارگذاری</span>
      <p className="mb-2 px-3 text-[11px] font-medium text-[#898989]">{label}</p>
      <div className="space-y-1">{Array.from({ length: 7 }, (_, index) => <Skeleton key={index} className="w-full" style={{ height: "2.75rem", opacity: 1 - index * 0.08 }} />)}</div>
    </div>
  );
}

/** Same shell as the loaded page (conversation sidebar, message area, composer) with placeholder content. */
function AssistantSkeleton() {
  return (
    <div className="grid min-h-[calc(100vh-10rem)] items-start lg:min-h-[calc(100vh-4rem)] lg:grid-cols-[18rem_minmax(0,1fr)] lg:border lg:border-[#B2AC88]" dir="rtl">
      <span className="sr-only" role="status">در حال بارگذاری</span>
      <div className="flex w-full items-center justify-between border border-[#B2AC88] bg-[#F2F0EF] px-4 py-3 lg:hidden" aria-hidden="true">
        <Skeleton className="skeleton--line" style={{ width: "8rem" }} />
        <Skeleton className="skeleton--line" style={{ width: "4rem" }} />
      </div>
      <aside className="assistant-sidebar relative hidden flex-col overflow-hidden lg:sticky lg:top-8 lg:flex lg:h-[calc(100vh-4rem)] lg:w-auto lg:border-l lg:border-[#B2AC88] lg:shadow-none" aria-hidden="true">
        <nav className="flex-1 px-3 pb-24 pt-3">
          <div className="mb-5 flex items-center gap-2">
            <Skeleton style={{ width: "2.75rem", height: "2.75rem" }} />
            <div className="flex flex-1 gap-1 border border-[#B2AC88] bg-white p-1">
              {[0, 1, 2].map((index) => <Skeleton key={index} className="flex-1" style={{ height: "2.25rem" }} />)}
            </div>
          </div>
          <AssistantListSkeleton />
        </nav>
        <Skeleton className="absolute bottom-5 left-5" style={{ width: "3.5rem", height: "3.5rem" }} />
      </aside>
      <section className="relative flex h-[calc(100dvh-10rem)] min-h-[32rem] flex-col overflow-hidden border border-[#B2AC88] bg-[#F2F0EF] lg:h-[calc(100dvh-4rem)] lg:border-0" aria-hidden="true">
        <div className="absolute left-3 top-3 flex items-center gap-2 md:left-4 md:top-4">
          <Skeleton style={{ width: "2.75rem", height: "2.75rem" }} />
          <Skeleton style={{ width: "2.75rem", height: "2.75rem" }} />
        </div>
        <div className="flex-1 space-y-5 overflow-hidden p-4 pt-20 md:p-7 md:pt-20">
          <AssistantMessagesSkeleton />
        </div>
        <div className="assistant-composer relative shrink-0 border-t border-[#B2AC88] bg-white p-3">
          <div className="flex items-start gap-2">
            <div className="relative min-w-0 flex-1 bg-[#F2F0EF]" style={{ height: "4.25rem" }}>
              <div className="absolute inset-x-3 bottom-1 flex items-center justify-between gap-3">
                <Skeleton style={{ width: "40%", height: "0.75rem" }} />
                <div className="flex gap-1">{[0, 1, 2].map((index) => <Skeleton key={index} style={{ width: "3.5rem", height: "1.5rem" }} />)}</div>
              </div>
            </div>
            <Skeleton className="self-stretch" style={{ width: "3rem", minHeight: "3rem" }} />
          </div>
        </div>
      </section>
    </div>
  );
}

export default function Assistant() {
  const { session } = useAuth();
  const desktopMenuToggle = useDesktopMenuToggle();
  const [search, setSearch] = useSearchParams();
  const training = search.get("mode") === "train" && isOrgAdmin(session?.role);
  const requestedConversationId = search.get("conversation");
  const requestedCallId = search.get("call_id");
  const temporaryRequested = search.get("temporary") === "true";
  const expandedCallId = search.get("source_call");
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [conversation, setConversation] = useState<ChatConversation | null>(null);
  const [ephemeral, setEphemeral] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const speechPrefixRef = useRef("");
  const [loading, setLoading] = useState(true);
  const conversationsRef = useRef<ChatConversation[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [messagesLoading, setMessagesLoading] = useState(false);
  conversationsRef.current = conversations;
  const initialLoadDoneRef = useRef(false);
  const loadedListKeyRef = useRef("");
  const [sendingRuns, setSendingRuns] = useState<Record<string, string | null>>({});
  const sendingRunsRef = useRef(sendingRuns);
  sendingRunsRef.current = sendingRuns;
  const [socketConnected, setSocketConnected] = useState(false);
  const conversationRunKey = ephemeral ? "ephemeral" : conversation?.id || "new";
  const conversationRunKeyRef = useRef(conversationRunKey);
  conversationRunKeyRef.current = conversationRunKey;
  const activeRunId = sendingRuns[conversationRunKey] === "pending" ? null : sendingRuns[conversationRunKey] || null;
  const sending = Object.prototype.hasOwnProperty.call(sendingRuns, conversationRunKey);
  const cancelRequestedConversationKeysRef = useRef(new Set<string>());
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [conversationsOpen, setConversationsOpen] = useState(false);
  const conversationView = search.get("conversation_view") === "archived" ? "archived" : "active";
  const [memories, setMemories] = useState<OrganizationMemory[]>([]);
  const [memoryStatus, setMemoryStatus] = useState(() => search.get("memory_status") || "draft");
  const [memoryCategory, setMemoryCategory] = useState(() => search.get("memory_category") || "");
  const [memoryInfoOpen, setMemoryInfoOpen] = useState(false);
  const [memoryFiltersOpen, setMemoryFiltersOpen] = useState(false);
  const [editingMemory, setEditingMemory] = useState<OrganizationMemory | null>(null);
  const [memoryEditTitle, setMemoryEditTitle] = useState("");
  const [memoryEditContent, setMemoryEditContent] = useState("");
  const memoryPanelOpen = training && search.get("memory_panel") !== "closed";
  const selectedMemoryId = search.get("memory");
  const [confirmation, setConfirmation] = useState<{ action: "archive" | "delete"; item: ChatConversation } | null>(null);
  const [messageEdit, setMessageEdit] = useState<{ message: ChatMessage; value: string } | null>(null);
  const [pendingMessageEdit, setPendingMessageEdit] = useState<{ message: ChatMessage; value: string } | null>(null);
  const [messageEditConfirmationOpen, setMessageEditConfirmationOpen] = useState(false);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [phases, setPhases] = useState<Record<string, string>>({});
  const messagesScrollerRef = useRef<HTMLDivElement>(null);
  const memoryPanelControlsRef = useRef<HTMLDivElement>(null);
  const selectedConversationIdRef = useRef<string | null>(null);
  const streamingRepliesRef = useRef(new Map<string, ChatMessage>());
  const socketRef = useRef<Socket | null>(null);
  const runDraftsRef = useRef(new Map<string, string>());
  const runConversationKeysRef = useRef(new Map<string, string>());
  const requestConversationKeysRef = useRef(new Map<string, string>());
  const joiningConversationIdsRef = useRef(new Set<string>());
  const bufferedRunEventsRef = useRef(new Map<string, any[]>());
  const ephemeralPendingContentRef = useRef("");
  const completionWaitersRef = useRef(new Map<string, (value: { message: ChatMessage; conversationTitle: string | null }) => void>());
  const completionRejectorsRef = useRef(new Map<string, (error: Error) => void>());
  const completedRunsRef = useRef(new Map<string, { message: ChatMessage; conversationTitle: string | null }>());
  const terminalRunsRef = useRef(new Set<string>());
  const sequenceRef = useRef(new Map<string, number>());
  const draftKey = `cbi.assistant.draft:${ephemeral ? "ephemeral" : conversation?.id || "new"}`;
  const loadedDraftKeyRef = useRef<string | null>(null);
  const userNearBottomRef = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const composerRef = useRef<HTMLFormElement>(null);
  const [showScrollToEnd, setShowScrollToEnd] = useState(false);
  const [contextOptions, setContextOptions] = useState<AssistantContextOptions | null>(null);
  const [attachments, setAttachments] = useState<AssistantMessageAttachments>(emptyAttachments);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionAnchor, setMentionAnchor] = useState<number | null>(null);
  const [mentionTab, setMentionTab] = useState<"mentions" | "dates" | "tools">(() => {
    const value = search.get("attach_tab");
    return value === "dates" || value === "tools" ? value : "mentions";
  });

  function setRunState(key: string, runId: string | null | undefined) {
    setSendingRuns((current) => withConversationRunState(current, key, runId));
  }

  function reconcileAcceptedUserMessage(accepted: any) {
    if (!accepted?.request_id || !accepted?.message_id || accepted.conversation_id !== selectedConversationIdRef.current) return;
    setMessages((current) => reconcileAcceptedMessage(current, String(accepted.request_id), String(accepted.message_id)));
  }

  function scrollToEnd() {
    const scroller = messagesScrollerRef.current;
    if (!scroller) return;
    userNearBottomRef.current = true;
    setShowScrollToEnd(false);
    scroller.scrollTo({ top: scroller.scrollHeight });
  }

  function handleMessagesScroll() {
    const scroller = messagesScrollerRef.current;
    if (!scroller) return;
    const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= 72;
    userNearBottomRef.current = nearBottom;
    setShowScrollToEnd(sending && !nearBottom);
  }

  function toggleCallSource(callId: string) {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      if (next.get("source_call") === callId) next.delete("source_call");
      else next.set("source_call", callId);
      return next;
    }, { replace: true });
  }

  function selectMentionTab(tab: "mentions" | "dates" | "tools") {
    setMentionTab(tab);
    setSearch((current) => {
      const next = new URLSearchParams(current);
      next.set("attach_tab", tab);
      return next;
    }, { replace: true });
  }

  function resizeInput() {
    const input = inputRef.current;
    if (!input) return;
    const maxHeight = 96;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, maxHeight)}px`;
    input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
  }

  function updateStreamingReply(conversationId: string, draftId: string, update: (message: ChatMessage) => ChatMessage) {
    const draft = streamingRepliesRef.current.get(conversationId);
    if (!draft || draft.id !== draftId) return;
    const nextDraft = update(draft);
    streamingRepliesRef.current.set(conversationId, nextDraft);
    if (selectedConversationIdRef.current !== conversationId) return;
    setMessages((current) => {
      const index = current.findIndex((item) => item.id === draftId);
      return index < 0 ? [...current, nextDraft] : current.map((item) => item.id === draftId ? nextDraft : item);
    });
  }

  async function loadMessages(item: ChatConversation) {
    try {
      setMessagesLoading(true);
      setError(null);
      selectedConversationIdRef.current = item.id;
      const rows = await request<ChatMessage[]>(`/v1/assistant/conversations/${item.id}/messages`);
      if (selectedConversationIdRef.current !== item.id) return;
      const streamingReply = streamingRepliesRef.current.get(item.id);
      setConversation(item);
      setSearch((current) => { const next = new URLSearchParams(current); next.set("conversation", item.id); next.delete("call_id"); next.delete("temporary"); return next; }, { replace: true });
      setEphemeral(false);
      setMessages(streamingReply ? [...rows, streamingReply] : rows);
      userNearBottomRef.current = true;
      setShowScrollToEnd(false);
      setConversationsOpen(false);
    } catch (err) {
      setError(assistantErrorMessage(err));
    } finally {
      if (selectedConversationIdRef.current === item.id) setMessagesLoading(false);
    }
  }
  async function create(callId: string | null = null, isCurrent: () => boolean = () => true) {
    const item = await request<ChatConversation>("/v1/assistant/conversations", { method: "POST", body: { call_id: training ? null : callId, mode: training ? "training" : "normal" } });
    if (!isCurrent()) {
      await request(`/v1/assistant/conversations/${item.id}`, { method: "DELETE" });
      throw new Error("انتخاب گفتگو پیش از ساخت آن تغییر کرد.");
    }
    setConversations((current) => [item, ...current]);
    selectedConversationIdRef.current = item.id;
    setConversation(item);
    setEphemeral(false);
    setMessages([]);
    setConversationsOpen(false);
    setSearch((current) => { const next = new URLSearchParams(current); next.set("conversation", item.id); next.set("conversation_view", "active"); next.delete("call_id"); next.delete("temporary"); return next; }, { replace: true });
    return item;
  }
  function createEphemeral() {
    if (ephemeral) return;
    selectedConversationIdRef.current = null;
    setConversation(null);
    setEphemeral(true);
    setMessages([]);
    userNearBottomRef.current = true;
    setShowScrollToEnd(false);
    setEditingId(null);
    setConversationsOpen(false);
    setError(null);
    setSearch((current) => { const next = new URLSearchParams(current); next.delete("conversation"); next.delete("call_id"); next.set("temporary", "true"); return next; }, { replace: true });
  }
  async function remove(item: ChatConversation) {
    try {
      setError(null);
      await request(`/v1/assistant/conversations/${item.id}`, { method: "DELETE" });
      const remaining = conversations.filter((current) => current.id !== item.id);
      setConversations(remaining);
      if (conversation?.id === item.id) {
        const next = remaining.find((current) => !current.archived_at);
        if (next) await loadMessages(next);
        else createEphemeral();
      }
    } catch (err) {
      setError(assistantErrorMessage(err));
    }
  }
  async function setArchived(item: ChatConversation, archived: boolean) {
    try {
      setError(null);
      const updated = await request<ChatConversation>(`/v1/assistant/conversations/${item.id}`, { method: "PATCH", body: { archived } });
      setConversations((current) => current.map((currentItem) => currentItem.id === updated.id ? updated : currentItem));
      if (conversation?.id === item.id && archived) {
        const next = conversations.find((current) => current.id !== item.id && !current.archived_at);
        if (next) await loadMessages(next);
        else createEphemeral();
      }
    } catch (err) {
      setError(assistantErrorMessage(err));
    }
  }
  async function setPinned(item: ChatConversation, pinned: boolean) {
    try {
      setError(null);
      const updated = await request<ChatConversation>(`/v1/assistant/conversations/${item.id}`, { method: "PATCH", body: { pinned } });
      setConversations((current) => current.map((currentItem) => currentItem.id === updated.id ? updated : currentItem));
      setConversation((current) => current?.id === updated.id ? updated : current);
    } catch (err) {
      setError(assistantErrorMessage(err));
    }
  }
  async function confirmConversationAction() {
    if (!confirmation) return;
    const { action, item } = confirmation;
    setConfirmation(null);
    if (action === "delete") await remove(item);
    else await setArchived(item, true);
  }
  async function rename(item: ChatConversation) {
    const nextTitle = title.trim();
    if (!nextTitle) return;
    try {
      setError(null);
      const updated = await request<ChatConversation>(`/v1/assistant/conversations/${item.id}`, { method: "PATCH", body: { title: nextTitle } });
      setConversations((current) => current.map((currentItem) => currentItem.id === updated.id ? updated : currentItem));
      setConversation((current) => current?.id === updated.id ? updated : current);
      setEditingId(null);
    } catch (err) {
      setError(assistantErrorMessage(err));
    }
  }
  async function loadMemories() {
    if (!training) { setMemories([]); return; }
    const params = new URLSearchParams();
    if (memoryStatus) params.set("status", memoryStatus);
    if (memoryCategory) params.set("category", memoryCategory);
    setMemories(await request<OrganizationMemory[]>(`/v1/assistant/memories?${params}`));
  }
  async function memoryAction(item: OrganizationMemory, action: "approve" | "reject" | "replace" | "archive") {
    try {
      setError(null);
      await request<OrganizationMemory>(`/v1/assistant/memories/${item.id}/${action}`, {
        method: "POST",
        body: { lock_version: item.lock_version, idempotency_key: crypto.randomUUID() },
      });
      await loadMemories();
    } catch (err) { setError(assistantErrorMessage(err)); }
  }
  async function saveMemoryDraft() {
    if (!editingMemory || !memoryEditTitle.trim() || !memoryEditContent.trim()) return;
    try {
      const updated = await request<OrganizationMemory>(`/v1/assistant/memories/${editingMemory.id}/draft`, {
        method: "PATCH",
        body: { lock_version: editingMemory.lock_version, title: memoryEditTitle.trim(), content: memoryEditContent.trim() },
      });
      setMemories((current) => current.map((item) => item.id === updated.id ? updated : item));
      setEditingMemory(null);
    } catch (err) { setError(assistantErrorMessage(err)); }
  }
  function setMemoryFilter(key: "memory_status" | "memory_category", value: string) {
    if (key === "memory_status") setMemoryStatus(value);
    else setMemoryCategory(value);
    setSearch((current) => { const next = new URLSearchParams(current); if (value) next.set(key, value); else next.delete(key); return next; }, { replace: true });
  }
  function setMemoryPanelOpen(open: boolean) {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      next.set("memory_panel", open ? "open" : "closed");
      return next;
    }, { replace: true });
  }
  function selectMemory(memoryId: string) {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      next.set("memory", memoryId);
      return next;
    }, { replace: true });
  }
  function selectAssistantTab(tab: "chat" | "archived" | "train") {
    const nextMode = tab === "train" ? "train" : "chat";
    const nextView = tab === "archived" ? "archived" : "active";
    selectedConversationIdRef.current = null;
    setSearch((current) => {
      const next = new URLSearchParams(current);
      next.set("mode", nextMode);
      next.set("conversation_view", nextView);
      next.delete("conversation");
      next.delete("call_id");
      next.delete("temporary");
      return next;
    });
  }
  useEffect(() => {
    let active = true;
    void (async () => {
      // Only the first load blanks the page; later changes reload just the list (tab switch) or the messages (conversation switch).
      const listKey = `${training}|${conversationView}|${session?.role}`;
      const needList = loadedListKeyRef.current !== listKey;
      try {
        if (!initialLoadDoneRef.current) setLoading(true);
        else if (needList) setListLoading(true);
        let rows = conversationsRef.current;
        if (needList) {
          const primaryRows = await request<ChatConversation[]>(`/v1/assistant/conversations?mode=${training ? "training" : "normal"}`);
          if (!active) return;
          rows = !training && conversationView === "archived" && isOrgAdmin(session?.role)
            ? [...primaryRows, ...(await request<ChatConversation[]>("/v1/assistant/conversations?mode=training"))].sort((first, second) => Date.parse(second.updated_at) - Date.parse(first.updated_at))
            : primaryRows;
          if (!active) return;
          setConversations(rows);
          loadedListKeyRef.current = listKey;
        }
        setListLoading(false);
        const selected = rows.find((item) => item.id === requestedConversationId);
        const callId = training ? null : requestedCallId;
        if (callId) await create(callId, () => active);
        else if (temporaryRequested) {
          selectedConversationIdRef.current = null;
          setConversation(null);
          setMessages([]);
          setEphemeral(true);
        }
        else if (selected) { if (needList || selectedConversationIdRef.current !== selected.id) await loadMessages(selected); }
        else if (requestedConversationId) {
          selectedConversationIdRef.current = null;
          setConversation(null);
          setMessages([]);
          setEphemeral(false);
          setError("گفتگوی درخواستی پیدا نشد.");
        }
        else if (conversationView === "archived") {
          setConversation(null);
          setMessages([]);
          setEphemeral(false);
        }
        else {
          const activeConversation = rows.find((item) => !item.archived_at);
          if (activeConversation) await loadMessages(activeConversation);
          else await create(null, () => active);
        }
      } catch (err) { if (active) setError(assistantErrorMessage(err)); }
      finally { if (active) { initialLoadDoneRef.current = true; setLoading(false); setListLoading(false); setMessagesLoading(false); } }
    })();
    return () => { active = false; };
  }, [training, conversationView, session?.role, requestedConversationId, requestedCallId, temporaryRequested]);
  useEffect(() => { setMemoryStatus(search.get("memory_status") || "draft"); }, [search.get("memory_status")]);
  useEffect(() => { setMemoryCategory(search.get("memory_category") || ""); }, [search.get("memory_category")]);
  useEffect(() => {
    const tab = search.get("attach_tab");
    setMentionTab(tab === "dates" || tab === "tools" ? tab : "mentions");
  }, [search.get("attach_tab")]);
  useEffect(() => {
    void loadMemories().catch((err) => setError(assistantErrorMessage(err)));
  }, [training, memoryStatus, memoryCategory]);
  useEffect(() => {
    if (!memoryInfoOpen && !memoryFiltersOpen) return;
    const closeControls = (event: MouseEvent) => {
      if (memoryPanelControlsRef.current?.contains(event.target as Node)) return;
      setMemoryInfoOpen(false);
      setMemoryFiltersOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMemoryInfoOpen(false);
      setMemoryFiltersOpen(false);
    };
    document.addEventListener("mousedown", closeControls);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeControls);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [memoryInfoOpen, memoryFiltersOpen]);
  useEffect(() => {
    void request<AssistantContextOptions>("/v1/assistant/context-options")
      .then(setContextOptions)
      .catch((err) => setError(assistantErrorMessage(err)));
  }, []);
  useEffect(() => {
    const socket = io({ path: "/socket.io", autoConnect: false, auth: { token: tokens.access() },
      reconnection: true, reconnectionAttempts: Infinity, timeout: 10000 });
    socketRef.current = socket;
    const messageForRun = (runId: string): string => {
      const known = runDraftsRef.current.get(runId);
      if (known) return known;
      const id = `draft-reply-${runId}`;
      runDraftsRef.current.set(runId, id);
      return id;
    };
    const markTerminalRun = (runId: string) => {
      terminalRunsRef.current.add(runId);
      window.setTimeout(() => {
        terminalRunsRef.current.delete(runId);
        sequenceRef.current.delete(runId);
        runConversationKeysRef.current.delete(runId);
        runDraftsRef.current.delete(runId);
      }, 30000);
    };
    const resolveCancelledRun = (runId: string, draftId: string, message?: ChatMessage) => {
      markTerminalRun(runId);
      const result = {
        message: message || { id: draftId, role: "assistant" as const, content: "پاسخ متوقف شد.", status: "cancelled", model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() },
        conversationTitle: null,
      };
      completedRunsRef.current.set(runId, result);
      completionWaitersRef.current.get(runId)?.(result);
      completionWaitersRef.current.delete(runId);
      window.setTimeout(() => completedRunsRef.current.delete(runId), 30000);
    };
    const applyEnvelope = (envelope: any) => {
      const runId = String(envelope?.run_id || "");
      const conversationId = envelope?.conversation_id ? String(envelope.conversation_id) : null;
      const event = String(envelope?.event || "");
      const payload = envelope?.payload || {};
      const runKey = runConversationKeysRef.current.get(runId) || conversationId || "ephemeral";
      if (runId && !isFreshRunSequence(sequenceRef.current.get(runId), Number(envelope.sequence || 0))) return;
      if (runId) sequenceRef.current.set(runId, Number(envelope.sequence || 0));
      if (runId && (event === "message:completed" || event === "done" || event === "cancelled")) markTerminalRun(runId);
      if (runKey !== conversationRunKeyRef.current) {
        if (event === "cancelled") {
          setRunState(runKey, null);
          resolveCancelledRun(runId, messageForRun(runId), payload.message as ChatMessage | undefined);
        } else if ((event === "message:completed" || event === "done") && payload.message) {
          setRunState(runKey, null);
          const result = {
            message: payload.message as ChatMessage,
            conversationTitle: payload.conversation_title || null,
          };
          if (result.message.memory_drafts?.length) {
            setMemories((current) => [...result.message.memory_drafts!, ...current.filter((item) => !result.message.memory_drafts!.some((draft) => draft.id === item.id))]);
          }
          if (conversationId && result.conversationTitle) {
            setConversations((current) => current.map((item) => item.id === conversationId ? { ...item, title: result.conversationTitle } : item));
          }
          completedRunsRef.current.set(runId, result);
          completionWaitersRef.current.get(runId)?.(result);
          completionWaitersRef.current.delete(runId);
          window.setTimeout(() => completedRunsRef.current.delete(runId), 30000);
        } else if (event === "message:completed" || event === "done") {
          setRunState(runKey, null);
          completionRejectorsRef.current.get(runId)?.(new Error("پاسخ دستیار کامل دریافت نشد. گفتگو را دوباره باز کنید."));
          completionRejectorsRef.current.delete(runId);
          completionWaitersRef.current.delete(runId);
        }
        return;
      }
      const draftId = messageForRun(runId);
      if (event === "delta" && payload.content) {
        setMessages((current) => {
          const existing = current.find((item) => item.id === draftId);
          const draft = existing || { id: draftId, role: "assistant" as const, content: "", status: "running" as const, model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() };
          const next = { ...draft, content: `${draft.content}${payload.content}` };
          return existing ? current.map((item) => item.id === draftId ? next : item) : [...current, next];
        });
      } else if (event === "replace" && payload.content !== undefined) {
        setMessages((current) => {
          const existing = current.find((item) => item.id === draftId);
          const draft = existing || { id: draftId, role: "assistant" as const, content: "", status: "running" as const, model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() };
          const next = { ...draft, content: payload.content };
          return existing ? current.map((item) => item.id === draftId ? next : item) : [...current, next];
        });
      } else if (event === "phase" && payload.label) {
        setPhases((current) => ({ ...current, [draftId]: payload.label }));
      } else if (["tool_started", "tool_completed", "tool_failed"].includes(event) && payload.tool_call_id) {
        const run: AssistantToolRun = { tool_call_id: payload.tool_call_id, name: payload.name, title: payload.title,
          status: payload.status || (event === "tool_started" ? "running" : event === "tool_failed" ? "failed" : "succeeded"),
          duration_ms: payload.duration_ms ?? null, summary: payload.summary ?? null,
          error_code: payload.error_code ?? null, charts: payload.charts || [], files: payload.files || [] };
        setMessages((current) => {
          const existing = current.find((item) => item.id === draftId);
          const draft = existing || { id: draftId, role: "assistant" as const, content: "", status: "running" as const, model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() };
          const next = { ...draft, tool_runs: [...(draft.tool_runs || []).filter((item) => item.tool_call_id !== run.tool_call_id), run] };
          return existing ? current.map((item) => item.id === draftId ? next : item) : [...current, next];
        });
      } else if (event === "message:completed" || event === "done") {
        const rawMessage = payload.message;
        if (!rawMessage) {
          setRunState(runKey, null);
          setPhases((current) => { const next = { ...current }; delete next[draftId]; return next; });
          return;
        }
        const message = rawMessage as ChatMessage;
        const result = { message, conversationTitle: payload.conversation_title || null };
        setMessages((current) => {
          const index = current.findIndex((item) => item.id === draftId);
          if (index >= 0) return current.map((item) => item.id === draftId ? message : item);
          if (current.some((item) => item.id === message.id)) return current;
          return [...current, message];
        });
        setRunState(runKey, null);
        setPhases((current) => { const next = { ...current }; delete next[draftId]; return next; });
        if (message.memory_drafts?.length) setMemories((current) => [...message.memory_drafts!, ...current.filter((item) => !message.memory_drafts!.some((draft) => draft.id === item.id))]);
        if (conversationId && payload.conversation_title) {
          setConversation((current) => current?.id === conversationId ? { ...current, title: payload.conversation_title } : current);
          setConversations((current) => current.map((item) => item.id === conversationId ? { ...item, title: payload.conversation_title } : item));
        }
        completedRunsRef.current.set(runId, result);
        completionWaitersRef.current.get(runId)?.(result);
        completionWaitersRef.current.delete(runId);
        window.setTimeout(() => completedRunsRef.current.delete(runId), 30000);
      } else if (event === "cancelled") {
        setRunState(runKey, null);
        const draftId = messageForRun(runId);
        const cancelledMessage: ChatMessage = payload.message as ChatMessage || { id: draftId, role: "assistant", content: "پاسخ متوقف شد.", status: "cancelled", model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() };
        setMessages((current) => {
          const index = current.findIndex((item) => item.id === draftId);
          if (index >= 0) return current.map((item) => item.id === draftId ? cancelledMessage : item);
          if (current.some((item) => item.id === cancelledMessage.id)) return current;
          return [...current, cancelledMessage];
        });
        setRunState(runKey, null);
        resolveCancelledRun(runId, draftId, cancelledMessage);
        setPhases((current) => { const next = { ...current }; delete next[draftId]; return next; });
      }
    };
    socket.on("connect", () => {
      setSocketConnected(true);
      const conversationId = selectedConversationIdRef.current;
      if (conversationId) {
        joiningConversationIdsRef.current.add(conversationId);
        void socket.timeout(15000).emitWithAck("assistant:conversation:join", { conversation_id: conversationId, after_sequence: 0 })
          .then((ack: any) => { if (!ack?.ok) { joiningConversationIdsRef.current.delete(conversationId); setError(ack?.code || "بازیابی گفتگو انجام نشد."); } })
          .catch(() => { joiningConversationIdsRef.current.delete(conversationId); setError("بازیابی گفتگو پس از اتصال مجدد انجام نشد."); });
      }
    });
    socket.on("disconnect", () => {
      setSocketConnected(false);
      if (sendingRunsRef.current.ephemeral !== undefined) {
        setRunState("ephemeral", null);
        if (ephemeralPendingContentRef.current) {
          localStorage.setItem("cbi.assistant.draft:ephemeral", ephemeralPendingContentRef.current);
          if (conversationRunKeyRef.current === "ephemeral") setText(ephemeralPendingContentRef.current);
        }
        if (conversationRunKeyRef.current === "ephemeral") {
          setError("اتصال چت موقت قطع شد. متن پیام حفظ شده؛ پس از اتصال دوباره آن را ارسال کنید.");
        }
        for (const [runId, key] of runConversationKeysRef.current) {
          if (key !== "ephemeral") continue;
          completionWaitersRef.current.delete(runId);
          completionRejectorsRef.current.get(runId)?.(new Error("اجرای چت موقت پس از قطع اتصال متوقف شد."));
          completionRejectorsRef.current.delete(runId);
          runConversationKeysRef.current.delete(runId);
        }
      }
    });
    socket.on("connect_error", async () => {
      setSocketConnected(false);
      if (await refreshSession()) {
        socket.auth = { token: tokens.access() };
        socket.connect();
      }
    });
    socket.on("assistant:message:accepted", (accepted: any) => {
      reconcileAcceptedUserMessage(accepted);
      if (accepted?.run_id && accepted?.request_id) {
        const runId = String(accepted.run_id);
        runDraftsRef.current.set(runId, `draft-reply-${accepted.request_id}`);
        const key = String(accepted.conversation_id || requestConversationKeysRef.current.get(String(accepted.request_id)) || "ephemeral");
        runConversationKeysRef.current.set(runId, key);
        setRunState(key, runId);
      }
    });
    socket.on("assistant:conversation:state", (state: any) => {
      const stateConversationId = String(state?.conversation_id || "");
      if (stateConversationId !== selectedConversationIdRef.current) {
        joiningConversationIdsRef.current.delete(stateConversationId);
        return;
      }
      const restored: ChatMessage[] = (state.messages || []).map((item: any) => ({ ...item, tool_runs: item.tool_runs || [], memory_drafts: item.memory_drafts || [] }));
      const completedDraftIds = new Set<string>(
        (state.completed_runs || []).map((run: any) => runDraftsRef.current.get(String(run.id))).filter(Boolean),
      );
      for (const run of state.active_runs || []) {
        if (terminalRunsRef.current.has(String(run.id))) continue;
        const draftId = messageForRun(String(run.id));
        runConversationKeysRef.current.set(String(run.id), String(state.conversation_id));
        setRunState(String(state.conversation_id), String(run.id));
        sequenceRef.current.set(String(run.id), 0);
        restored.push({ id: draftId, role: "assistant", content: "", status: "running", model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() });
      }
      setMessages((current) => mergeSnapshotMessages(current, restored, completedDraftIds));
      joiningConversationIdsRef.current.delete(stateConversationId);
      const completedRunIds = new Set<string>();
      for (const completed of state.completed_runs || []) {
        const runId = String(completed.id);
        completedRunIds.add(runId);
        const result = {
          message: completed.message as ChatMessage,
          conversationTitle: completed.conversation_title || null,
        };
        runConversationKeysRef.current.set(runId, stateConversationId);
        sequenceRef.current.set(runId, Number(completed.sequence || 0));
        markTerminalRun(runId);
        completedRunsRef.current.set(runId, result);
        completionWaitersRef.current.get(runId)?.(result);
        completionWaitersRef.current.delete(runId);
        window.setTimeout(() => completedRunsRef.current.delete(runId), 30000);
        setSendingRuns((current) => {
          if (current[stateConversationId] !== runId) return current;
          const next = { ...current };
          delete next[stateConversationId];
          return next;
        });
      }
      const activeRuns = (state.active_runs || []).filter((run: any) => !terminalRunsRef.current.has(String(run.id)));
      const activeRunIds = new Set(activeRuns.map((run: any) => String(run.id)));
      for (const run of activeRuns) {
        for (const event of orderUniqueRunEvents(run.events || [], bufferedRunEventsRef.current.get(String(run.id)) || [])) {
          applyEnvelope({ ...event, run_id: run.id, conversation_id: state.conversation_id });
        }
        bufferedRunEventsRef.current.delete(String(run.id));
      }
      for (const [runId, buffered] of bufferedRunEventsRef.current) {
        if (activeRunIds.has(runId) || completedRunIds.has(runId)) continue;
        sequenceRef.current.set(runId, 0);
        runConversationKeysRef.current.set(runId, stateConversationId);
        for (const event of orderUniqueRunEvents([], buffered)) {
          applyEnvelope({ ...event, run_id: runId, conversation_id: stateConversationId });
        }
        bufferedRunEventsRef.current.delete(runId);
      }
    });
    for (const event of ["delta", "replace", "phase", "tool_started", "tool_completed", "tool_failed", "message:completed", "done", "cancelled"]) {
      socket.on(`assistant:${event}`, (envelope: any) => {
        const conversationId = envelope?.conversation_id ? String(envelope.conversation_id) : null;
        const runId = String(envelope?.run_id || "");
        const terminal = event === "message:completed" || event === "done" || event === "cancelled";
        if (!terminal && conversationId && joiningConversationIdsRef.current.has(conversationId)) {
          const buffered = bufferedRunEventsRef.current.get(runId) || [];
          buffered.push(envelope);
          bufferedRunEventsRef.current.set(runId, buffered);
          return;
        }
        applyEnvelope(envelope);
      });
    }
    socket.on("assistant:error", (payload: any) => {
      const runId = String(payload?.run_id || "");
      const key = runId ? runConversationKeysRef.current.get(runId) || "ephemeral" : conversationRunKeyRef.current;
      if (key === conversationRunKeyRef.current) setError(payload?.message || "اتصال دستیار با خطا روبه‌رو شد.");
      if (runId) setRunState(key, null);
    });
    socket.connect();
    return () => {
      socket.removeAllListeners();
      socket.disconnect();
      socketRef.current = null;
    };
  }, []);
  useEffect(() => {
    const socket = socketRef.current;
    if (!socket?.connected || !conversation?.id || ephemeral || joiningConversationIdsRef.current.has(conversation.id)) return;
    const conversationId = conversation.id;
    joiningConversationIdsRef.current.add(conversationId);
    void socket.timeout(15000).emitWithAck("assistant:conversation:join", { conversation_id: conversationId, after_sequence: 0 })
      .then((ack: any) => { if (!ack?.ok) { joiningConversationIdsRef.current.delete(conversationId); setError(ack?.code || "بازیابی گفتگو انجام نشد."); } })
      .catch(() => { joiningConversationIdsRef.current.delete(conversationId); setError("بازیابی گفتگو انجام نشد."); });
    return () => { joiningConversationIdsRef.current.delete(conversationId); socket.emit("assistant:conversation:leave", { conversation_id: conversationId }); };
  }, [conversation?.id, ephemeral, socketConnected]);
  useEffect(() => {
    if (loadedDraftKeyRef.current !== draftKey) {
      setText(localStorage.getItem(draftKey) || "");
      loadedDraftKeyRef.current = draftKey;
      return;
    }
    if (text) localStorage.setItem(draftKey, text);
    else localStorage.removeItem(draftKey);
  }, [draftKey, text]);
  useEffect(() => {
    if (userNearBottomRef.current) scrollToEnd();
    else setShowScrollToEnd(sending);
  }, [messages, sending]);
  useEffect(() => {
    if (!conversationsOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConversationsOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [conversationsOpen]);
  useEffect(() => {
    if (!confirmation) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfirmation(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [confirmation]);
  useEffect(() => {
    if (!mentionOpen) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (event.target instanceof Element && event.target.closest("[data-date-picker-panel]")) return;
      if (!composerRef.current?.contains(event.target as Node)) setMentionOpen(false);
    };
    document.addEventListener("click", closeOnOutsideClick);
    return () => document.removeEventListener("click", closeOnOutsideClick);
  }, [mentionOpen]);

  async function interruptMessage() {
    if (!sending) return;
    cancelRequestedConversationKeysRef.current.add(conversationRunKey);
    if (!activeRunId) return;
    try {
      const acknowledged = await socketRef.current?.timeout(15000).emitWithAck("assistant:message:cancel", { run_id: activeRunId });
      if (!acknowledged?.ok) setError(acknowledged?.code || "توقف پاسخ انجام نشد.");
    } catch (err) {
      setError(assistantErrorMessage(err));
    }
  }

  async function sendBranch(content: string, history: ChatMessage[], branchAttachments: AssistantMessageAttachments = attachments) {
    let runKey = ephemeral ? "ephemeral" : conversation?.id || "new";
    setRunState(runKey, "pending");
    setError(null);
    const messageAttachments = branchAttachments;
    const requestId = crypto.randomUUID();
    const optimistic: ChatMessage = { id: `draft-user-${requestId}`, role: "user", content, status: "succeeded", model: null, sources: null, attachments: messageAttachments, tool_runs: [], created_at: new Date().toISOString() };
    const draftReply: ChatMessage = { id: `draft-reply-${requestId}`, role: "assistant", content: "", status: "running", model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() };
    if (ephemeral) ephemeralPendingContentRef.current = content;
    let activeConversationId: string | null = null;
    try {
      const active = ephemeral ? null : conversation ?? await create(null, () => conversationRunKeyRef.current === runKey);
      activeConversationId = active?.id ?? null;
      const nextRunKey = active?.id || "ephemeral";
      if (nextRunKey !== runKey) {
        setRunState(runKey, null);
        runKey = nextRunKey;
        setRunState(runKey, "pending");
      }
      setMessages([...history, optimistic, draftReply]);
      if (active) streamingRepliesRef.current.set(active.id, draftReply);
      const socket = socketRef.current;
      if (!socket?.connected) throw new Error("اتصال زنده دستیار برقرار نیست. پس از اتصال دوباره ارسال کنید.");
      requestConversationKeysRef.current.set(requestId, runKey);
      const requestPayload = {
        request_id: requestId,
        conversation_id: active?.id ?? null,
        idempotency_key: crypto.randomUUID(),
        content: optimistic.content,
        attachments: messageAttachments,
      };
      const acknowledged = active
        ? await socket.timeout(15000).emitWithAck("assistant:message:send", requestPayload)
        : await socket.timeout(15000).emitWithAck("assistant:ephemeral:send", {
            ...requestPayload,
            call_id: null,
            history: history.slice(-24).map((item) => ({ role: item.role, content: item.content.slice(0, 1500) })),
          });
      if (!acknowledged?.ok || !acknowledged?.run_id) throw new Error(acknowledged?.code || "ارسال پیام انجام نشد.");
      reconcileAcceptedUserMessage(acknowledged);
      const runId = String(acknowledged.run_id);
      runDraftsRef.current.set(runId, draftReply.id);
      runConversationKeysRef.current.set(runId, runKey);
      setRunState(runKey, runId);
      if (cancelRequestedConversationKeysRef.current.has(runKey)) {
        cancelRequestedConversationKeysRef.current.delete(runKey);
        const cancelAck = await socket.timeout(15000).emitWithAck("assistant:message:cancel", { run_id: runId });
        if (!cancelAck?.ok) throw new Error(cancelAck?.code || "توقف پاسخ انجام نشد.");
      }
      const reply = await new Promise<{ message: ChatMessage; conversationTitle: string | null }>((resolve, reject) => {
        const cached = completedRunsRef.current.get(runId);
        if (cached) {
          completedRunsRef.current.delete(runId);
          resolve(cached);
        } else {
          const timer = window.setTimeout(() => {
            completionWaitersRef.current.delete(runId);
            completionRejectorsRef.current.delete(runId);
            reject(new Error("زمان انتظار برای پاسخ دستیار به پایان رسید. گفتگو را دوباره باز کنید تا وضعیت بازیابی شود."));
          }, 31 * 60 * 1000);
          completionWaitersRef.current.set(runId, (result) => { window.clearTimeout(timer); completionRejectorsRef.current.delete(runId); resolve(result); });
          completionRejectorsRef.current.set(runId, (error) => { window.clearTimeout(timer); reject(error); });
        }
      });
      ephemeralPendingContentRef.current = "";
      if (active) streamingRepliesRef.current.delete(active.id);
      if (active && reply.conversationTitle) {
        setConversation((current) => current?.id === active.id ? { ...current, title: reply.conversationTitle } : current);
        setConversations((current) => current.map((item) => item.id === active.id ? { ...item, title: reply.conversationTitle } : item));
      }
      if (conversationRunKeyRef.current === runKey) setAttachments(emptyAttachments());
      if (active) {
        const rows = await request<ChatMessage[]>(`/v1/assistant/conversations/${active.id}/messages`);
        if (selectedConversationIdRef.current === active.id) setMessages(reply.message.status === "cancelled" && !rows.some((item) => item.id === reply.message.id) ? [...rows, reply.message] : rows);
        setConversations((current) => current.map((item) => item.id === active.id ? { ...item, title: reply.conversationTitle || item.title, updated_at: reply.message.created_at } : item));
        if (reply.conversationTitle) setConversation((current) => current?.id === active.id ? { ...current, title: reply.conversationTitle } : current);
      }
    } catch (err) {
      const message = assistantErrorMessage(err);
      const failedReply = (item: ChatMessage) => ({ ...item, content: message || "پاسخ دستیار آماده نشد.", status: "failed" as const });
      if (activeConversationId) updateStreamingReply(activeConversationId, draftReply.id, failedReply);
      else setMessages((current) => current.map((item) => item.id === draftReply.id ? failedReply(item) : item));
      if (conversationRunKeyRef.current === runKey) setError(message);
    } finally {
      cancelRequestedConversationKeysRef.current.delete(runKey);
      requestConversationKeysRef.current.delete(draftReply.id.replace("draft-reply-", ""));
      setRunState(runKey, null);
    }
  }

  async function replaceMessageBranch(target: ChatMessage, content: string) {
    const index = messages.findIndex((item) => item.id === target.id);
    if (index < 0) return;
    const history = messages.slice(0, index).filter((item) => item.status !== "running");
    if (!ephemeral && conversation && !target.id.startsWith("draft-")) {
      await request(`/v1/assistant/conversations/${conversation.id}/messages/${target.id}/tail`, { method: "DELETE" });
    }
    setMessageEdit(null);
    setPendingMessageEdit(null);
    setMessageEditConfirmationOpen(false);
    await sendBranch(content.trim(), history, target.attachments || emptyAttachments());
  }

  async function retryMessage(message: ChatMessage) {
    if (sending) return;
    const assistantIndex = messages.findIndex((item) => item.id === message.id);
    const userMessage = [...messages.slice(0, assistantIndex)].reverse().find((item) => item.role === "user");
    if (!userMessage) return;
    try {
      await replaceMessageBranch(userMessage, userMessage.content);
    } catch (err) {
      setError(assistantErrorMessage(err));
      setRunState(conversationRunKey, null);
    }
  }

  async function copyMessage(message: ChatMessage) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessageId(message.id);
      window.setTimeout(() => setCopiedMessageId((current) => current === message.id ? null : current), 1600);
    } catch {
      setError("کپی پیام انجام نشد.");
    }
  }

  function requestMessageEdit() {
    if (!messageEdit?.value.trim() || sending) return;
    const index = messages.findIndex((item) => item.id === messageEdit.message.id);
    const hasLaterMessages = index >= 0 && index < messages.length - 1;
    if (hasLaterMessages) {
      setPendingMessageEdit(messageEdit);
      setMessageEditConfirmationOpen(true);
      return;
    }
    void replaceMessageBranch(messageEdit.message, messageEdit.value).catch((err) => {
      setError(assistantErrorMessage(err));
      setRunState(conversationRunKey, null);
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || sending) return;
    if (!socketConnected) {
      setError("اتصال زنده دستیار برقرار نیست. ارسال پیام تا برقراری اتصال متوقف شد.");
      return;
    }
    if (!training && Boolean(attachments.from_date) !== Boolean(attachments.to_date)) {
      setError("برای بازه زمانی، تاریخ شروع و پایان را کامل انتخاب کنید.");
      setMentionOpen(true);
      selectMentionTab("dates");
      return;
    }
    const content = text.trim();
    window.dispatchEvent(new Event("assistant-message-sent"));
    const history = messages.filter((item) => item.status !== "running");
    setText("");
    requestAnimationFrame(resizeInput);
    await sendBranch(content, history);
  }
  function exportMessages() {
    const completedMessages = messages.filter((message) => message.status !== "running" && message.content.trim());
    if (!completedMessages.length) return;
    const heading = ephemeral ? "چت موقت" : conversation?.title?.trim() || "گفتگوی جدید";
    const transcript = completedMessages.map((message) => {
      const role = message.role === "user" ? "کاربر" : "دستیار";
      const timestamp = fmt.dateTime(message.created_at);
      return `${role} - ${timestamp}\n${message.content.trim()}`;
    }).join("\n\n--------------------\n\n");
    downloadTextFile(`${safeDownloadName(heading, "conversation")}.txt`, `${heading}\n\n${transcript}\n`);
  }
  const mentionStart = mentionAnchor ?? -1;
  const mentionQuery = mentionStart >= 0 && text[mentionStart] === "@" && !text.slice(mentionStart + 1).includes("\n") ? text.slice(mentionStart + 1).trim().toLocaleLowerCase("fa") : "";
  const mentionActive = mentionStart >= 0 && text[mentionStart] === "@" && text.slice(mentionStart + 1).length <= 80 && !text.slice(mentionStart + 1).includes("\n");
  const matchingOperators = isOrgAdmin(session?.role) ? (contextOptions?.operators || []).filter((item) => `${item.label} ${item.extension || ""}`.toLocaleLowerCase("fa").includes(mentionQuery)) : [];
  const matchingConversations = (contextOptions?.conversations || []).filter((item) => item.id !== conversation?.id && item.label.toLocaleLowerCase("fa").includes(mentionQuery));
  function completeMention() {
    if (!mentionActive) return;
    setText(text.slice(0, mentionStart).trimEnd());
    setMentionAnchor(null);
    setMentionOpen(false);
    requestAnimationFrame(() => {
      resizeInput();
      inputRef.current?.focus();
    });
  }
  function messageAttachmentLabels(message: ChatMessage): string[] {
    const selected = message.attachments;
    if (!selected) return [];
    const labels: string[] = [];
    if (selected.operator_id) {
      const operator = contextOptions?.operators.find((item) => item.id === selected.operator_id);
      labels.push(`اپراتور: ${operator?.label || selected.operator_id}`);
    }
    selected.conversation_ids.forEach((id) => {
      const attachedConversation = contextOptions?.conversations.find((item) => item.id === id);
      labels.push(`گفتگو: ${attachedConversation?.label || id}`);
    });
    if (selected.from_date && selected.to_date) {
      labels.push(`بازه: ${fmt.date(selected.from_date)} تا ${fmt.date(selected.to_date)}`);
    }
    selected.tool_names.forEach((name) => {
      const tool = contextOptions?.tools.find((item) => item.name === name);
      labels.push(`ابزار: ${tool?.title || name}`);
    });
    return labels;
  }
  function renderConversation(item: ChatConversation) {
    const isActive = conversation?.id === item.id;
    const isProcessing = sendingRuns[item.id] !== undefined;
    const archived = Boolean(item.archived_at);
    const pinned = Boolean(item.pinned_at);
    return <div key={item.id} className={`assistant-sidebar-item group relative w-full transition-colors duration-200 ${isActive ? "is-active bg-[#4B6E48]/10 font-bold text-[#3E5C3B]" : "text-[#4B6E48]/90"}`}>
      {isActive && editingId !== item.id ? <span className="absolute inset-y-2 right-0 w-[3px] bg-[#4B6E48]" aria-hidden="true" /> : null}
      {editingId === item.id ? <form className="flex min-h-11 w-full items-center gap-1 p-1.5" onSubmit={(event) => { event.preventDefault(); void rename(item); }}><input autoFocus className="min-w-0 flex-1 border border-[#B2AC88] bg-[#F2F0EF] px-2 py-1 text-sm text-[#4B6E48] outline-none" value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") { setEditingId(null); setTitle(""); } }} aria-label="نام گفتگو" /><button type="button" className="px-2 py-1 text-xs font-bold text-[#898989] hover:bg-[#F2F0EF] hover:text-[#4B6E48]" onClick={() => { setEditingId(null); setTitle(""); }}>انصراف</button><button type="submit" className="px-2 py-1 text-xs font-bold text-[#4B6E48] hover:bg-[#B2AC88] hover:text-white">ذخیره</button></form> : <button type="button" className={`flex min-h-11 w-full items-center gap-3 py-2.5 pr-3 pl-3 text-right text-sm transition-[padding] ${archived ? "group-hover:pl-28 group-focus-within:pl-28" : "group-hover:pl-36 group-focus-within:pl-36"}`} onClick={() => void loadMessages(item)}>{isProcessing ? <ConversationProcessingIndicator active={isActive} /> : <ChatIcon active={isActive} />}<span className="min-w-0 flex-1 truncate">{item.title || "گفتگوی جدید"}</span></button>}
      {editingId !== item.id && <div className="pointer-events-none absolute inset-y-0 left-1 flex items-center opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-[#898989] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" aria-label="ویرایش گفتگو" title="ویرایش گفتگو" onClick={() => { setTitle(item.title || ""); setEditingId(item.id); }}><EditIcon /></button>{!archived ? <button type="button" className={`inline-flex h-8 w-8 items-center justify-center transition hover:bg-[#B2AC88] hover:text-[#4B6E48] ${pinned ? "text-[#4B6E48]" : "text-[#898989]"}`} aria-label={pinned ? "برداشتن پین گفتگو" : "پین کردن گفتگو"} title={pinned ? "برداشتن پین گفتگو" : "پین کردن گفتگو"} onClick={() => void setPinned(item, !pinned)}><PinIcon pinned={pinned} /></button> : null}<button type="button" className="inline-flex h-8 w-8 items-center justify-center text-[#898989] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" aria-label={archived ? "بازیابی گفتگو" : "آرشیو گفتگو"} title={archived ? "بازیابی گفتگو" : "آرشیو گفتگو"} onClick={() => archived ? void setArchived(item, false) : setConfirmation({ action: "archive", item })}><ArchiveIcon restore={archived} /></button><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-rose-600 transition hover:bg-rose-50" aria-label="حذف گفتگو" title="حذف گفتگو" onClick={() => setConfirmation({ action: "delete", item })}><TrashIcon /></button></div>}
    </div>;
  }
  function renderMemoryPanel() {
    return <div className="flex h-full flex-col bg-white">
      <div ref={memoryPanelControlsRef} className="relative flex shrink-0 items-center justify-between gap-3 border-b border-[#B2AC88] p-4">
        <h2 className="font-bold text-[#4B6E48]">مموری سازمانی</h2>
        <div className="flex items-center gap-1">
          <IconTooltip label="توضیحات مموری سازمانی"><button type="button" className={`inline-flex h-9 w-9 items-center justify-center transition hover:bg-[#F2F0EF] ${memoryInfoOpen ? "bg-[#F2F0EF] text-[#4B6E48]" : "text-[#898989]"}`} onClick={() => { setMemoryInfoOpen((current) => !current); setMemoryFiltersOpen(false); }} aria-label="نمایش توضیحات مموری سازمانی" aria-expanded={memoryInfoOpen} aria-controls="organization-memory-info"><InfoIcon /></button></IconTooltip>
          <IconTooltip label="فیلتر مموری‌ها"><button type="button" className={`inline-flex h-9 w-9 items-center justify-center transition hover:bg-[#F2F0EF] ${memoryFiltersOpen ? "bg-[#F2F0EF] text-[#4B6E48]" : "text-[#898989]"}`} onClick={() => { setMemoryFiltersOpen((current) => !current); setMemoryInfoOpen(false); }} aria-label="فیلتر مموری‌ها" aria-expanded={memoryFiltersOpen} aria-controls="organization-memory-filters"><FilterIcon /></button></IconTooltip>
          <button type="button" className="inline-flex h-9 w-9 shrink-0 items-center justify-center text-[#4B6E48] transition hover:bg-[#F2F0EF]" onClick={() => setMemoryPanelOpen(false)} aria-label="بستن پنل مموری"><CloseIcon /></button>
        </div>
        {memoryInfoOpen ? <div id="organization-memory-info" className="absolute inset-x-3 top-full z-20 mt-2 border border-[#B2AC88] bg-white p-3 text-xs leading-5 text-[#898989] shadow-lg">فقط موارد تأییدشده در پاسخ‌ها و تحلیل‌های جدید استفاده می‌شوند.</div> : null}
        {memoryFiltersOpen ? <div id="organization-memory-filters" className="absolute inset-x-3 top-full z-20 mt-2 grid gap-2 border border-[#B2AC88] bg-white p-3 shadow-lg"><select className="input h-9 min-w-0 py-1 text-xs" value={memoryStatus} onChange={(event) => setMemoryFilter("memory_status", event.target.value)}><option value="draft">پیش‌نویس‌ها</option><option value="active">فعال</option><option value="archived">آرشیوشده</option><option value="rejected">ردشده</option></select><select className="input h-9 min-w-0 py-1 text-xs" value={memoryCategory} onChange={(event) => setMemoryFilter("memory_category", event.target.value)}><option value="">همه دسته‌ها</option><option value="organization_profile">معرفی سازمان</option><option value="products_services">محصولات و خدمات</option><option value="terminology">اصطلاحات</option><option value="policies">سیاست‌ها</option><option value="analysis_rules">قواعد تحلیل</option><option value="freeform">سایر</option></select></div> : null}
      </div>
      <div className="sidebar-scroll flex-1 space-y-2 overflow-y-auto p-3">
        {memories.map((item) => <article key={item.id} className={`border p-3 text-sm transition ${selectedMemoryId === item.id ? "border-[#4B6E48] bg-[#EEF2E9]" : "border-[#D8D3B9] bg-[#F2F0EF]"}`} onClick={() => selectMemory(item.id)}>
          {editingMemory?.id === item.id ? <div className="space-y-2"><input className="input" value={memoryEditTitle} onChange={(event) => setMemoryEditTitle(event.target.value)} /><textarea className="input min-h-28" value={memoryEditContent} onChange={(event) => setMemoryEditContent(event.target.value)} /><div className="flex justify-end gap-2"><button type="button" className="px-3 py-1 text-xs" onClick={() => setEditingMemory(null)}>انصراف</button><button type="button" className="bg-[#4B6E48] px-3 py-1 text-xs font-bold text-white" onClick={() => void saveMemoryDraft()}>ذخیره پیش‌نویس</button></div></div> : <><div className="flex items-start justify-between gap-3"><div className="min-w-0"><strong className="text-[#4B6E48]">{item.title}</strong><p className="mt-1 whitespace-pre-wrap leading-6">{item.content}</p></div><span className="shrink-0 border border-[#B2AC88] bg-white px-2 py-1 text-[10px]">نسخه {fmt.int(item.version)}</span></div><div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-[#898989]"><span>{item.category}</span><span>{item.applies_to.join(" · ")}</span>{item.conflicts.length ? <span className="font-bold text-amber-700">دارای تعارض</span> : null}</div><div className="mt-3 flex flex-wrap justify-end gap-2">{item.status === "draft" ? <><button type="button" className="border border-[#B2AC88] px-2 py-1 text-xs" onClick={() => { setEditingMemory(item); setMemoryEditTitle(item.title); setMemoryEditContent(item.content); }}>ویرایش</button><button type="button" className="border border-rose-300 px-2 py-1 text-xs text-rose-700" onClick={() => void memoryAction(item, "reject")}>رد</button><button type="button" className="bg-[#4B6E48] px-2 py-1 text-xs font-bold text-white" onClick={() => void memoryAction(item, item.conflicts.length ? "replace" : "approve")}>{item.conflicts.length ? "جایگزینی" : "تأیید"}</button></> : null}{item.status === "active" ? <><button type="button" className="border border-[#B2AC88] px-2 py-1 text-xs" onClick={() => { setEditingMemory(item); setMemoryEditTitle(item.title); setMemoryEditContent(item.content); }}>نسخه جدید</button><button type="button" className="border border-[#B2AC88] px-2 py-1 text-xs" onClick={() => void memoryAction(item, "archive")}>آرشیو</button></> : null}</div></>}
        </article>)}
        {!memories.length ? <p className="py-10 text-center text-xs text-[#898989]">موردی در این بخش وجود ندارد.</p> : null}
      </div>
    </div>;
  }
  if (loading) return <AssistantSkeleton />;
  return <div className={`grid min-h-[calc(100vh-10rem)] items-start lg:min-h-[calc(100vh-4rem)] lg:border lg:border-[#B2AC88] ${memoryPanelOpen ? "lg:grid-cols-[18rem_minmax(0,1fr)_22rem]" : "lg:grid-cols-[18rem_minmax(0,1fr)]"}`} dir="rtl">
    <button type="button" className="flex w-full items-center justify-between border border-[#B2AC88] bg-[#F2F0EF] px-4 py-3 text-[#4B6E48] lg:hidden" onClick={() => setConversationsOpen(true)} aria-expanded={conversationsOpen} aria-controls="assistant-conversations-menu">
      <span className="min-w-0 truncate text-sm font-bold">{ephemeral ? "چت موقت" : conversation?.title || "گفتگوی جدید"}</span>
      <span className="flex shrink-0 items-center gap-2 text-xs"><MenuIcon /> گفتگوها</span>
    </button>
    <button type="button" className={`fixed inset-0 z-40 bg-slate-950/45 backdrop-blur-sm transition-opacity lg:hidden ${conversationsOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"}`} onClick={() => setConversationsOpen(false)} aria-label="بستن فهرست گفتگوها" tabIndex={conversationsOpen ? 0 : -1} />
    <aside id="assistant-conversations-menu" className={`assistant-sidebar fixed inset-y-0 right-0 z-50 flex w-[min(88vw,19rem)] flex-col overflow-hidden border-0 text-white shadow-2xl transition-transform duration-300 ease-out lg:sticky lg:top-8 lg:z-auto lg:h-[calc(100vh-4rem)] lg:w-auto lg:translate-x-0 lg:border-l lg:border-[#B2AC88] lg:shadow-none ${conversationsOpen ? "translate-x-0" : "translate-x-full"}`} role="dialog" aria-modal={conversationsOpen ? "true" : undefined} aria-label="فهرست گفتگوها">
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-[#B2AC88] px-4 lg:hidden">
        <span className="text-sm font-bold text-[#4B6E48]">گفتگوها</span>
        <button type="button" className="inline-flex h-10 w-10 items-center justify-center text-[#4B6E48] transition hover:bg-[#F2F0EF]" onClick={() => setConversationsOpen(false)} aria-label="بستن فهرست گفتگوها"><MenuIcon close /></button>
      </div>
      <nav className="sidebar-scroll flex-1 overflow-y-auto px-3 pb-24 pt-3" aria-label="فهرست گفتگوها">
        <div className="mb-5 flex items-center gap-2">
          {desktopMenuToggle ? <button type="button" className="assistant-panel-menu-toggle hidden h-11 w-11 shrink-0 items-center justify-center border border-[#B2AC88] bg-white text-[#4B6E48] shadow-[0_8px_20px_rgba(75,110,72,0.14)] transition hover:-translate-y-0.5 hover:border-[#4B6E48] hover:bg-[#4B6E48] hover:text-[#F2F0EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] lg:inline-flex" onClick={desktopMenuToggle.toggle} aria-label={desktopMenuToggle.open ? "مخفی کردن منوی اصلی" : "نمایش منوی اصلی"} aria-expanded={desktopMenuToggle.open} aria-controls="client-desktop-menu"><MenuIcon close={desktopMenuToggle.open} /></button> : null}
          <div className="flex flex-1 border border-[#B2AC88] bg-white p-1" role="tablist" aria-label="نوع گفتگوها">
            <button type="button" role="tab" aria-selected={!training && conversationView === "active"} className={`min-h-9 flex-1 px-2 text-xs font-bold transition ${!training && conversationView === "active" ? "bg-[#4B6E48] text-[#F2F0EF]" : "text-[#4B6E48] hover:bg-[#F2F0EF]"}`} onClick={() => selectAssistantTab("chat")}>چت‌ها</button>
            <button type="button" role="tab" aria-selected={!training && conversationView === "archived"} className={`min-h-9 flex-1 px-2 text-xs font-bold transition ${!training && conversationView === "archived" ? "bg-[#4B6E48] text-[#F2F0EF]" : "text-[#4B6E48] hover:bg-[#F2F0EF]"}`} onClick={() => selectAssistantTab("archived")}>آرشیوها</button>
            {isOrgAdmin(session?.role) ? <button type="button" role="tab" aria-selected={training} className={`min-h-9 flex-1 px-2 text-xs font-bold transition ${training ? "bg-[#4B6E48] text-[#F2F0EF]" : "text-[#4B6E48] hover:bg-[#F2F0EF]"}`} onClick={() => selectAssistantTab("train")}>آموزش</button> : null}
          </div>
        </div>
        {listLoading ? <AssistantListSkeleton label={conversationView === "archived" ? "گفتگوهای آرشیوشده" : "گفتگوهای فعال"} /> : conversationView === "active" ? <>{conversations.some((item) => item.pinned_at && !item.archived_at) ? <div className="mb-6"><p className="mb-2 px-3 text-[11px] font-medium tracking-wide text-[#898989]">پین‌شده‌ها</p><div className="space-y-0.5">{conversations.filter((item) => item.pinned_at && !item.archived_at).sort((first, second) => Date.parse(second.pinned_at || "") - Date.parse(first.pinned_at || "")).map(renderConversation)}</div></div> : null}<div className="mb-6">
          <p className="mb-2 px-3 text-[11px] font-medium tracking-wide text-[#898989]">گفتگوهای فعال</p>
          {conversations.some((item) => !item.archived_at && !item.pinned_at) ? <div className="space-y-0.5">{conversations.filter((item) => !item.archived_at && !item.pinned_at).map(renderConversation)}</div> : <p className="px-3 py-8 text-center text-xs text-[#898989]">گفتگوی فعال دیگری وجود ندارد.</p>}
        </div></> : <div className="mb-6"><p className="mb-2 px-3 text-[11px] font-medium tracking-wide text-[#898989]">گفتگوهای آرشیوشده</p>{conversations.some((item) => item.archived_at) ? <div className="space-y-0.5">{conversations.filter((item) => item.archived_at).map(renderConversation)}</div> : <p className="px-3 py-8 text-center text-xs text-[#898989]">گفتگوی آرشیوشده‌ای وجود ندارد.</p>}</div>}
      </nav>
      <button type="button" className="absolute bottom-5 left-5 z-10 inline-flex h-14 w-14 items-center justify-center bg-[#4B6E48] text-[#F2F0EF] shadow-[0_10px_30px_rgba(75,110,72,0.28)] transition duration-200 hover:-translate-y-0.5 hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]" onClick={() => void create()} aria-label="گفتگوی جدید" title="گفتگوی جدید">
        <PlusIcon />
      </button>
    </aside>
    <section className="relative flex h-[calc(100dvh-10rem)] min-h-[32rem] flex-col overflow-hidden border border-[#B2AC88] bg-[#F2F0EF] lg:h-[calc(100dvh-4rem)] lg:border-0">
      <div className="absolute inset-x-3 top-3 z-20 md:inset-x-4 md:top-4">
        <ErrorBox message={error} className="absolute right-0 top-0 mb-0 max-w-[calc(100%-6rem)] shadow-sm" />
        <div className="absolute left-0 top-0 flex items-center gap-2">
          {!socketConnected ? <span className="inline-flex h-11 items-center gap-2 border border-[#B2AC88] bg-white px-3 text-xs font-bold text-[#898989]" role="status"><span className="h-3 w-3 animate-spin rounded-full border-2 border-[#B2AC88] border-t-[#4B6E48]" />در حال اتصال</span> : null}
          {training ? <button type="button" className={`inline-flex h-11 items-center gap-2 border px-3 text-xs font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] ${memoryPanelOpen ? "border-[#4B6E48] bg-[#4B6E48] text-white" : "border-[#B2AC88] bg-white text-[#4B6E48] hover:border-[#4B6E48] hover:bg-[#F2F0EF]"}`} onClick={() => setMemoryPanelOpen(!memoryPanelOpen)} aria-expanded={memoryPanelOpen} aria-controls="organization-memory-panel"><span>مموری‌ها</span>{memories.length ? <span className={`inline-flex min-w-5 items-center justify-center px-1 text-[10px] ${memoryPanelOpen ? "bg-white text-[#4B6E48]" : "bg-[#F2F0EF] text-[#4B6E48]"}`}>{fmt.int(memories.length)}</span> : null}</button> : null}
          {!training ? <IconTooltip label="چت موقت بدون ذخیره‌سازی">
            <button type="button" className={`inline-flex h-11 w-11 items-center justify-center border transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] ${ephemeral ? "border-[#4B6E48] bg-[#4B6E48] text-[#F2F0EF]" : "border-[#B2AC88] bg-white text-[#4B6E48] hover:border-[#4B6E48] hover:bg-[#F2F0EF]"}`} onClick={createEphemeral} aria-label="شروع چت موقت بدون ذخیره‌سازی" aria-pressed={ephemeral}><TemporaryChatIcon /></button>
          </IconTooltip> : null}
          <IconTooltip label="خروجی متن پیام‌ها">
            <button type="button" className="inline-flex h-11 w-11 items-center justify-center border border-[#B2AC88] bg-white text-[#4B6E48] transition hover:border-[#4B6E48] hover:bg-[#F2F0EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:text-[#898989] disabled:opacity-50" onClick={exportMessages} aria-label="خروجی متن پیام‌ها" disabled={!messages.some((message) => message.status !== "running" && message.content.trim())}><DownloadIcon /></button>
          </IconTooltip>
        </div>
      </div>
      <div ref={messagesScrollerRef} className="sidebar-scroll flex-1 space-y-5 overflow-y-auto p-4 md:p-7" onScroll={handleMessagesScroll}>
        {ephemeral ? <div className="mx-auto flex max-w-xl items-center gap-2 border border-[#B2AC88] bg-white px-3 py-2 text-xs text-[#4B6E48]" role="status"><TemporaryChatIcon /><span>این چت ذخیره نمی‌شود و با بستن یا ترک صفحه از بین می‌رود.</span></div> : null}
        {messagesLoading ? <AssistantMessagesSkeleton /> : null}
        {!messagesLoading && messages.length === 0 ? <div className="mx-auto max-w-lg pt-10 text-center text-[#898989]"><CallStateArt section={training ? "training" : ephemeral ? "temporary" : "assistant"} className="mx-auto mb-3" /><h1 className="mb-3 text-xl font-bold text-[#4B6E48]">{training ? "آموزش دستیار" : ephemeral ? "چت موقت" : "دستیار تماس‌ها"}</h1><p>{training ? "درباره سازمان، محصولات، اصطلاحات و معیارهای تحلیل توضیح دهید تا دستیار با سؤال‌های تکمیلی پیش‌نویس مموری بسازد." : "درباره تماس‌ها، متن مکالمات، تحلیل‌ها و عملکرد اپراتورها سؤال کنید."}</p></div> : null}
        {(messagesLoading ? [] : messages).map((message) => {
          const user = message.role === "user";
          const attachedLabels = messageAttachmentLabels(message);
          const charts = (message.tool_runs || []).flatMap((run) => run.charts || []);
          const actionClass = "inline-flex h-7 w-7 items-center justify-center text-[#898989] transition hover:bg-white hover:text-[#4B6E48] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#4B6E48] disabled:opacity-50";
          if (!user && message.status === "running" && !message.content) {
            return <div key={message.id} className="flex w-full justify-start" dir="ltr"><TypingIndicator label={phases[message.id]} /></div>;
          }
          const actions = <>
            <span className="flex items-center gap-0.5" dir="rtl">
              {user && message.status !== "running" ? <button type="button" className={actionClass} disabled={sending} onClick={() => setMessageEdit({ message, value: message.content })} aria-label="ویرایش پیام" title="ویرایش پیام"><EditIcon /></button> : null}
              {message.status !== "running" && message.content ? <button type="button" className={actionClass} onClick={() => void copyMessage(message)} aria-label={copiedMessageId === message.id ? "پیام کپی شد" : "کپی پیام"} title={copiedMessageId === message.id ? "کپی شد" : "کپی پیام"}><CopyIcon checked={copiedMessageId === message.id} /></button> : null}
              {!user && message.status === "failed" ? <button type="button" className={`${actionClass} hover:text-rose-700`} disabled={sending} onClick={() => void retryMessage(message)} aria-label="تلاش مجدد" title="تلاش مجدد"><RetryIcon /></button> : null}
            </span>
            <time className="px-1 text-[10px] leading-none text-[#898989]" dateTime={message.created_at} title={fmt.dateTime(message.created_at)}>{fmt.time(message.created_at)}</time>
          </>;
          return <ConversationBubble key={message.id} side={user ? "user" : "assistant"} wide={Boolean(message.sources?.length || charts.length)} actions={messageEdit?.message.id === message.id ? null : actions}>
              {user && messageEdit?.message.id === message.id ? <div className="space-y-2">
                <textarea autoFocus rows={3} className="input min-h-24 resize-y bg-white text-slate-900" value={messageEdit.value} onChange={(event) => setMessageEdit({ message, value: event.target.value })} onKeyDown={(event) => { if (event.key === "Escape") setMessageEdit(null); }} aria-label="ویرایش پیام" />
                <div className="flex justify-end gap-2"><button type="button" className="border border-[#B2AC88] bg-transparent px-3 py-1.5 text-xs font-bold text-[#F2F0EF] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" onClick={() => setMessageEdit(null)}>انصراف</button><button type="button" className="border border-[#F2F0EF] bg-[#F2F0EF] px-3 py-1.5 text-xs font-bold text-[#4B6E48] transition hover:border-white hover:bg-white disabled:cursor-not-allowed disabled:opacity-50" disabled={!messageEdit.value.trim() || sending} onClick={requestMessageEdit}>ثبت و دریافت پاسخ جدید</button></div>
              </div> : <>
              {user && attachedLabels.length ? <div className="mb-2 flex flex-wrap gap-1.5" aria-label="موارد متصل به پیام">{attachedLabels.map((label) => <span key={label} className="inline-flex min-h-6 items-center border border-[#D8D3B9] bg-[#F2F0EF] px-2 py-0.5 text-[11px] font-bold leading-5 text-[#365033]">{label}</span>)}</div> : null}
              {!user ? <ToolTimeline runs={message.tool_runs || []} active={message.status === "running"} /> : null}
              {message.status === "running" && !message.content ? <TypingIndicator label={phases[message.id]} /> : <MarkdownMessage content={message.content} />}
              {!user ? <AssistantCharts charts={charts} /> : null}{!user ? <AssistantExportFiles runs={message.tool_runs || []} /> : null}
              {message.sources?.length ? <CallSources sources={message.sources} expandedCallId={expandedCallId} onToggle={toggleCallSource} /> : null}
              </>}
          </ConversationBubble>;
        })}
      </div>
      {showScrollToEnd ? <button type="button" className="absolute bottom-[7rem] left-1/2 z-20 inline-flex h-11 w-11 -translate-x-1/2 items-center justify-center rounded-full border border-[#B2AC88] bg-white text-[#4B6E48] transition hover:border-[#4B6E48] hover:bg-[#F2F0EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]" onClick={() => scrollToEnd()} aria-label="رفتن به انتهای گفتگو" title="رفتن به انتهای گفتگو"><ScrollDownIcon /></button> : null}
      <form ref={composerRef} className="assistant-composer relative shrink-0 border-t border-[#B2AC88] bg-white" onSubmit={submit}>
        {!training && mentionOpen ? <AssistantContextPicker tab={mentionTab} onTabChange={selectMentionTab} onClose={() => { setMentionOpen(false); inputRef.current?.focus(); }} attachments={attachments} onChange={setAttachments} options={contextOptions}>
          {mentionTab === "mentions" ? <>
              {matchingOperators.length ? <><p className="px-3 pb-1 pt-2 text-[11px] font-bold text-[#898989]">اپراتورها</p>{matchingOperators.map((item) => <button key={item.id} type="button" className={`flex w-full items-center justify-between px-3 py-2 text-right text-sm ${attachments.operator_id === item.id ? "bg-[#4B6E48] text-white" : "hover:bg-[#F2F0EF]"}`} onClick={() => { setAttachments((current) => ({ ...current, operator_id: item.id })); completeMention(); }}><span>{item.label}</span><span className="text-xs opacity-70">{item.extension ? `داخلی ${item.extension}` : "اپراتور"}</span></button>)}</> : null}
              {matchingConversations.length ? <><p className="px-3 pb-1 pt-2 text-[11px] font-bold text-[#898989]">گفتگوهای قبلی</p>{matchingConversations.map((item) => <button key={item.id} type="button" className={`flex w-full items-center justify-between px-3 py-2 text-right text-sm ${attachments.conversation_ids.includes(item.id) ? "bg-[#4B6E48] text-white" : "hover:bg-[#F2F0EF]"}`} onClick={() => { setAttachments((current) => ({ ...current, conversation_ids: current.conversation_ids.includes(item.id) ? current.conversation_ids : [...current.conversation_ids, item.id] })); completeMention(); }}><span className="truncate">{item.label}</span><span className="shrink-0 text-xs opacity-70">{item.archived ? "آرشیو" : fmt.date(item.updated_at)}</span></button>)}</> : null}
              {!matchingOperators.length && !matchingConversations.length ? <p className="px-3 py-6 text-center text-xs text-[#898989]">نتیجه‌ای پیدا نشد.</p> : null}
            </> : null}
        </AssistantContextPicker> : null}
        {!training ? <AssistantAttachmentChips attachments={attachments} options={contextOptions} onChange={setAttachments} /> : null}
<div className={`flex flex-col transition ${listening ? "bg-[#E8F0E5]" : "bg-[#F2F0EF]"}`}><textarea ref={inputRef} rows={1} className="input block h-[3rem] min-h-[3rem] w-full resize-none overflow-y-hidden border-0 bg-transparent px-3 pb-1 pt-3 text-sm text-slate-900 !shadow-none focus:!border-0 focus:!shadow-none focus:!outline-none" value={text} onChange={(event) => { const value = event.target.value; setText(value); const newAt = value.lastIndexOf("@"); let activeAnchor = mentionAnchor; if (newAt >= 0 && newAt === value.length - 1 && newAt !== mentionAnchor) { activeAnchor = newAt; setMentionAnchor(newAt); } const active = activeAnchor !== null && value[activeAnchor] === "@" && value.slice(activeAnchor + 1).length <= 80 && !value.slice(activeAnchor + 1).includes("\n"); if (active) { setMentionOpen(true); selectMentionTab("mentions"); } else if (mentionTab === "mentions") { setMentionAnchor(null); setMentionOpen(false); } requestAnimationFrame(resizeInput); }} onKeyDown={(event) => { if (event.key === "Escape" && mentionOpen) { event.preventDefault(); setMentionAnchor(null); setMentionOpen(false); } else if (event.ctrlKey && event.key === "Enter") { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={listening ? "در حال شنیدن گفتار فارسی…" : "سؤال خود را بنویسید…"} /><div className="assistant-composer-actions flex min-w-0 items-center gap-2 px-3 pb-3 pt-2"><div className="flex shrink-0 items-center gap-1.5"><PersianSpeechInputButton className={`inline-flex h-8 items-center gap-1.5 border px-2.5 text-xs font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:opacity-50 ${listening ? "border-[#4B6E48] bg-[#4B6E48] text-white" : "border-[#B2AC88] bg-white text-[#4B6E48] hover:border-[#4B6E48] hover:bg-[#E8F0E5]"}`} onTranscript={({ final, interim }) => { setText(`${speechPrefixRef.current}${speechPrefixRef.current && (final || interim) ? " " : ""}${final}${final && interim ? " " : ""}${interim}`); requestAnimationFrame(resizeInput); inputRef.current?.focus(); }} onListeningChange={(active) => { if (active) speechPrefixRef.current = text; setListening(active); }} />{!training ? <><button type="button" className="inline-flex h-8 items-center gap-1.5 border border-[#B2AC88] bg-white px-2.5 text-xs font-bold text-[#4B6E48] transition hover:border-[#4B6E48] hover:bg-[#E8F0E5] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#4B6E48]" aria-haspopup="dialog" aria-expanded={mentionOpen && mentionTab === "dates"} onClick={() => { setMentionAnchor(null); setMentionOpen((current) => mentionTab === "dates" ? !current : true); selectMentionTab("dates"); }}><CalendarIcon />بازه زمانی</button><button type="button" className="inline-flex h-8 items-center gap-1.5 border border-[#B2AC88] bg-white px-2.5 text-xs font-bold text-[#4B6E48] transition hover:border-[#4B6E48] hover:bg-[#E8F0E5] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#4B6E48]" aria-haspopup="dialog" aria-expanded={mentionOpen && mentionTab === "tools"} onClick={() => { setMentionAnchor(null); setMentionOpen((current) => mentionTab === "tools" ? !current : true); selectMentionTab("tools"); }}><ToolsIcon />ابزارها</button></> : null}</div><p className="pointer-events-none hidden min-w-0 flex-1 truncate px-1 text-[11px] text-[#898989] sm:block">{listening ? "در حال دریافت گفتار فارسی…" : !text ? <TypingPromptGuide /> : null}</p><span className="flex-1 sm:hidden" /><button type={sending ? "button" : "submit"} onClick={sending ? () => void interruptMessage() : undefined} className="inline-flex h-9 shrink-0 items-center justify-center gap-2 bg-[#4B6E48] px-4 text-sm font-bold text-[#F2F0EF] transition hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:bg-[#B2AC88] disabled:text-white" aria-label={sending ? "قطع پاسخ" : "ارسال پیام"} title={sending ? "قطع پاسخ" : socketConnected ? "ارسال پیام (Ctrl+Enter)" : "در انتظار اتصال زنده"} disabled={sending ? false : !text.trim() || !socketConnected}>{sending ? <StopIcon /> : <SendIcon />}<span>{sending ? "توقف" : "ارسال"}</span></button></div></div>
      </form>
    </section>
    {memoryPanelOpen ? <><button type="button" className="fixed inset-0 z-40 bg-slate-950/45 backdrop-blur-sm lg:hidden" onClick={() => setMemoryPanelOpen(false)} aria-label="بستن پنل مموری" /><aside id="organization-memory-panel" className="fixed inset-y-0 left-0 z-50 w-[min(92vw,24rem)] border-r border-[#B2AC88] shadow-2xl lg:sticky lg:top-8 lg:z-auto lg:h-[calc(100vh-4rem)] lg:w-auto lg:shadow-none" aria-label="مموری سازمانی">{renderMemoryPanel()}</aside></> : null}
    <ConfirmDialog
      open={Boolean(confirmation)}
      title={confirmation?.action === "delete" ? "حذف گفتگو" : "آرشیو گفتگو"}
      description={confirmation?.action === "delete" ? "آیا از حذف این گفتگو مطمئن هستید؟ این عملیات قابل بازگشت نیست." : "آیا از آرشیو کردن این گفتگو مطمئن هستید؟"}
      confirmLabel={confirmation?.action === "delete" ? "حذف" : "آرشیو"}
      destructive={confirmation?.action === "delete"}
      onCancel={() => setConfirmation(null)}
      onConfirm={() => void confirmConversationAction()}
    />
    <ConfirmDialog
      open={messageEditConfirmationOpen}
      title="ویرایش پیام قبلی"
      description="با ویرایش این پیام، تمام پیام‌های بعد از آن برای همیشه حذف می‌شوند و دستیار بر اساس متن جدید دوباره پاسخ می‌دهد. ادامه می‌دهید؟"
      confirmLabel="ویرایش و حذف ادامه گفتگو"
      destructive
      onCancel={() => { setMessageEditConfirmationOpen(false); setPendingMessageEdit(null); }}
      onConfirm={() => {
        if (!pendingMessageEdit) return;
        void replaceMessageBranch(pendingMessageEdit.message, pendingMessageEdit.value).catch((err) => {
          setError(assistantErrorMessage(err));
          setRunState(conversationRunKey, null);
        });
      }}
    />
  </div>;
}
