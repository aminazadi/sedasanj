import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { chart, palette } from "@cbi/web-shared/theme";
import { Icon } from "@iconify/react";
import alarmClockIcon from "@iconify-icons/lucide/alarm-clock";
import barChartIcon from "@iconify-icons/lucide/chart-no-axes-column";
import bullseyeIcon from "@iconify-icons/lucide/target";
import repeatButtonIcon from "@iconify-icons/lucide/refresh-cw";
import starIcon from "@iconify-icons/lucide/star";
import telephoneIcon from "@iconify-icons/lucide/phone";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmt, INTENT_LABELS, refreshSession, request, STATUS_LABELS, tokens } from "../api";
import { CAN_EDIT_TASKS, CAN_HEAR_AUDIO, isOrgAdmin, useAuth } from "../auth";
import FollowUpTaskCard from "../components/FollowUpTaskCard";
import OperatorCoachSection from "../components/OperatorCoachSection";
import AudioWaveformPlayer from "../components/AudioWaveformPlayer";
import ConversationBubble from "../components/ConversationBubble";
import ConfirmDialog from "../components/ConfirmDialog";
import {
  ErrorBox,
  OutcomeBadge,
  ProcessingCard,
  SentimentBadge,
  StatusBadge,
  TrajectoryBadge,
} from "../components/Widgets";
import type { AsrTranscriptRevision, CallDetail, CorrectionStatus, DualPartySentiment, FollowUpTask, OperatorScore, ProcessingEvent, Utterance } from "../types";
import { downloadTextFile } from "../utils/download";
import { CallStateArt, type CallStateKind, type CallStateSection } from "../components/CallStateArt";

const NER_LABELS: Record<string, string> = {
  persons: "افراد",
  dates: "تاریخ‌ها",
  amounts: "مبالغ",
  phone_numbers: "شماره‌ها",
  organizations: "سازمان‌ها",
};

const DIRECTION_LABELS: Record<string, string> = {
  inbound: "ورودی",
  outbound: "خروجی",
  internal: "داخلی",
};

const TURN_MERGE_GAP_MS = 1200;
const SPEAKER_COLORS = [chart.primary, chart.secondary];

/** Phone number with the phonebook title (when there is one) above it. */
function CallParty({ number, name }: { number: string | null; name?: string | null }) {
  return (
    <span className="inline-flex flex-col items-start leading-tight">
      {name ? <bdi className="block w-full text-right text-sm font-bold sm:text-base">{name}</bdi> : null}
      <bdi dir="ltr">{number ? fmt.digits(number) : "—"}</bdi>
    </span>
  );
}

function CopyIcon({ checked = false }: { checked?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
      {checked ? <path d="m5 12 4 4L19 6" /> : <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" /></>}
    </svg>
  );
}

function cleanTranscriptText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function buildConversationTurns(utterances: Utterance[]): Utterance[] {
  const ordered = [...utterances].sort(
    (left, right) => left.t_start_ms - right.t_start_ms || left.channel - right.channel,
  );
  const turns: Utterance[] = [];
  for (const utterance of ordered) {
    const text = cleanTranscriptText(utterance.text);
    if (!text) continue;
    const current = { ...utterance, text };
    const previous = turns.at(-1);
    if (
      previous &&
      previous.channel === current.channel &&
      current.t_start_ms <= previous.t_end_ms + TURN_MERGE_GAP_MS
    ) {
      const overlaps = current.t_start_ms <= previous.t_end_ms;
      const mergedText =
        overlaps && (current.text === previous.text || previous.text.endsWith(current.text))
          ? previous.text
          : overlaps && current.text.startsWith(previous.text)
            ? current.text
            : `${previous.text} ${current.text}`;
      turns[turns.length - 1] = {
        ...previous,
        t_end_ms: Math.max(previous.t_end_ms, current.t_end_ms),
        text: mergedText,
      };
    } else {
      turns.push(current);
    }
  }
  return turns;
}

function intervalUnionDuration(utterances: Utterance[]): number {
  const intervals = utterances
    .map((item) => [Math.max(0, item.t_start_ms), Math.max(item.t_start_ms, item.t_end_ms)] as const)
    .filter(([start, end]) => end > start)
    .sort((left, right) => left[0] - right[0] || left[1] - right[1]);
  let total = 0;
  let start = 0;
  let end = 0;
  for (const interval of intervals) {
    if (interval[0] > end) {
      total += Math.max(0, end - start);
      [start, end] = interval;
    } else {
      end = Math.max(end, interval[1]);
    }
  }
  return total + Math.max(0, end - start);
}

function clampScore(value: number | undefined): number {
  return Math.round(Math.max(0, Math.min(1, value ?? 0)) * 100);
}

function MetricCard({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
  hint: string;
  icon: ReactNode;
}) {
  return (
    <div className="call-metric-card p-4 transition duration-300 hover:-translate-y-0.5">
      <div className="relative z-10 mb-3 flex items-start justify-between gap-3">
        <span className="text-xs font-medium text-slate-600">{label}</span>
        <span className="flex h-14 w-14 items-center justify-center" aria-hidden="true">
          {icon}
        </span>
      </div>
      <div className="relative z-10 text-2xl font-extrabold tracking-tight text-slate-900">{value}</div>
      <p className="relative z-10 mt-1 text-[11px] leading-5 text-slate-500">{hint}</p>
    </div>
  );
}

function SectionTitle({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="font-bold text-slate-800">{title}</h2>
        {description ? <p className="mt-1 text-xs text-slate-400">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

function EmptyState({
  icon,
  message,
  state = "empty",
  compact = false,
  className = "",
}: {
  icon: CallStateSection;
  compact?: boolean;
  message: string;
  state?: CallStateKind;
  className?: string;
}) {
  return (
    <div className={`flex flex-col items-center justify-center gap-2 bg-slate-50 px-5 py-6 text-center ${className}`}>
      <CallStateArt section={icon} kind={state} compact={compact} />
      <p className={`max-w-md text-sm leading-6 ${state === "failed" ? "text-[#B5543F]" : "text-slate-400"}`} role={state === "empty" ? undefined : "status"}>{message}</p>
    </div>
  );
}

function ActionTooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden w-max max-w-52 -translate-x-1/2 border border-[color:var(--line)] bg-[#F2F0EF] px-2.5 py-1.5 text-[11px] font-normal leading-5 text-[#000000] shadow-lg group-hover:block group-focus-within:block"
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}

const CALL_ACTION_CLASS = "flex h-10 w-10 items-center justify-center border border-[#898989] bg-white text-[#000000] transition hover:bg-[#B2AC88] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:opacity-40";

function CircularAudioProgress({ progress }: { progress: number | null }) {
  const radius = 8;
  const circumference = 2 * Math.PI * radius;
  const normalizedProgress = progress === null ? 25 : Math.max(0, Math.min(100, progress));

  return (
    <svg
      className={`h-6 w-6 -rotate-90 ${progress === null ? "animate-spin" : ""}`}
      viewBox="0 0 24 24"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={progress ?? undefined}
    >
      <circle cx="12" cy="12" r={radius} fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.5" />
      <circle
        cx="12"
        cy="12"
        r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - normalizedProgress / 100)}
      />
    </svg>
  );
}

function SkeletonLine({ className = "" }: { className?: string }) {
  return <span className={`block rounded-full bg-slate-200 ${className}`} aria-hidden="true" />;
}

function CallDetailSkeleton() {
  return (
    <div className="space-y-5" aria-busy="true" aria-live="polite">
      <div className="flex items-center justify-center gap-2 rounded-xl border border-blue-100 bg-brand-50 px-4 py-3 text-sm font-medium text-brand-700">
        <span className="h-2 w-2 animate-pulse rounded-full bg-brand-500" />
        درحال استخراج اطلاعات ...
      </div>

      <section className="card relative overflow-hidden p-5 sm:p-6">
        <div className="absolute inset-x-0 top-0 h-1 bg-slate-200" />
        <div className="mb-5 flex items-center justify-between border-b border-slate-100 pb-4">
          <SkeletonLine className="h-3 w-36" />
          <SkeletonLine className="h-6 w-24" />
        </div>
        <div className="flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
          <div className="flex items-center gap-3">
            <span className="h-12 w-12 shrink-0 animate-pulse rounded-2xl bg-slate-200" />
            <div className="space-y-3">
              <SkeletonLine className="h-3 w-24" />
              <SkeletonLine className="h-6 w-64 max-w-[65vw]" />
              <SkeletonLine className="h-3 w-48 max-w-[55vw]" />
            </div>
          </div>
          <div className="flex gap-2">
            <SkeletonLine className="h-9 w-32" />
            <SkeletonLine className="h-9 w-24" />
            <SkeletonLine className="hidden h-9 w-16 sm:block" />
          </div>
        </div>
      </section>

      <section className="card overflow-hidden !p-0">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <div className="space-y-2">
            <SkeletonLine className="h-4 w-32" />
            <SkeletonLine className="h-3 w-44" />
          </div>
          <SkeletonLine className="h-7 w-24" />
        </div>
        <div className="h-1 bg-slate-100" />
        <div className="grid gap-4 px-4 py-5 sm:grid-cols-4 sm:px-6">
          {[0, 1, 2, 3].map((step) => (
            <div key={step} className="flex items-center gap-3 sm:block sm:text-center">
              <span className="h-8 w-8 shrink-0 animate-pulse rounded-full bg-slate-200 sm:mx-auto sm:mb-3 sm:block" />
              <div className="w-full space-y-2 sm:flex sm:flex-col sm:items-center">
                <SkeletonLine className="h-3 w-24" />
                <SkeletonLine className="h-2.5 w-28" />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-3 flex items-start justify-between">
              <SkeletonLine className="h-3 w-24" />
              <span className="h-9 w-9 animate-pulse rounded-xl bg-slate-200" />
            </div>
            <SkeletonLine className="h-7 w-20" />
            <SkeletonLine className="mt-2 h-2.5 w-32" />
          </div>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-5">
        <div className="card xl:col-span-3">
          <div className="mb-5 flex items-start justify-between">
            <div className="space-y-2">
              <SkeletonLine className="h-4 w-36" />
              <SkeletonLine className="h-3 w-64 max-w-[55vw]" />
            </div>
            <SkeletonLine className="h-8 w-24" />
          </div>
          <div className="flex h-64 items-end gap-3 border-b border-r border-slate-100 px-4 pb-3">
            {[38, 62, 46, 75, 58, 82, 66].map((height, index) => (
              <span key={index} className="flex-1 animate-pulse rounded-t-lg bg-slate-200" style={{ height: `${height}%` }} />
            ))}
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <SkeletonLine className="h-10 w-full rounded-xl" />
            <SkeletonLine className="h-10 w-full rounded-xl" />
          </div>
        </div>
        <div className="card xl:col-span-2">
          <div className="space-y-2">
            <SkeletonLine className="h-4 w-28" />
            <SkeletonLine className="h-3 w-48" />
          </div>
          <div className="flex h-64 items-center justify-center">
            <span className="h-44 w-44 animate-pulse rounded-full border-[28px] border-slate-200" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <SkeletonLine className="h-16 w-full rounded-xl" />
            <SkeletonLine className="h-16 w-full rounded-xl" />
          </div>
        </div>
      </section>

      <section className="card">
        <div className="mb-5 space-y-2">
          <SkeletonLine className="h-4 w-28" />
          <SkeletonLine className="h-3 w-56" />
        </div>
        <div className="flex h-52 items-end gap-2 border-b border-slate-100 px-2">
          {[42, 68, 34, 78, 52, 88, 46, 64, 38, 72, 55, 84].map((height, index) => (
            <span key={index} className="flex-1 animate-pulse rounded-t bg-slate-200" style={{ height: `${height}%` }} />
          ))}
        </div>
      </section>

      <section className="grid items-stretch gap-4 lg:grid-cols-3">
        <div className="card h-full lg:col-span-2">
          <div className="mb-5 space-y-2">
            <SkeletonLine className="h-4 w-28" />
            <SkeletonLine className="h-3 w-48" />
          </div>
          <div className="space-y-4 rounded-xl border border-slate-100 bg-slate-50 p-4">
            {["ml-auto w-4/5", "mr-auto w-3/4", "ml-auto w-2/3", "mr-auto w-5/6"].map((width, index) => (
              <div key={index} className={`rounded-2xl border border-slate-100 bg-white p-4 ${width}`}>
                <SkeletonLine className="mb-3 h-2.5 w-20" />
                <SkeletonLine className="mb-2 h-3 w-full" />
                <SkeletonLine className="h-3 w-4/5" />
              </div>
            ))}
          </div>
        </div>
        <aside className="space-y-4">
          {["h-44", "h-32", "h-48"].map((height, index) => (
            <div key={index} className={`card ${height}`}>
              <SkeletonLine className="mb-5 h-4 w-32" />
              <div className="space-y-3">
                <SkeletonLine className="h-3 w-full" />
                <SkeletonLine className="h-3 w-5/6" />
                <SkeletonLine className="h-3 w-2/3" />
              </div>
            </div>
          ))}
        </aside>
      </section>
    </div>
  );
}

function sentimentChartData(profile: DualPartySentiment | null | undefined) {
  if (!profile?.caller) return [];
  const timeline = [
    ...profile.caller.timeline.map((window) => ({ window, party: "مشتری" as const })),
    ...(profile.agent?.timeline ?? []).map((window) => ({ window, party: "اپراتور" as const })),
  ];
  if (timeline.length) {
    const points = new Map<number, { stage: string; مشتری?: number; اپراتور?: number }>();
    for (const { window, party } of timeline) {
      const midpointSeconds = Math.round((window.t_start_ms + window.t_end_ms) / 2000);
      const point = points.get(midpointSeconds) ?? {
        stage: fmt.digits(
          `${String(Math.floor(midpointSeconds / 60)).padStart(2, "0")}:${String(midpointSeconds % 60).padStart(2, "0")}`,
        ),
      };
      point[party] = clampScore(window.valence);
      points.set(midpointSeconds, point);
    }
    return [...points.entries()].sort(([left], [right]) => left - right).map(([, point]) => point);
  }
  const pointValence = (point: { label: string; score: number }) => {
    const base: Record<string, number> = {
      angry: 0,
      sad: 0.25,
      neutral: 0.5,
      satisfied: 0.75,
      happy: 1,
    };
    return clampScore(0.5 + ((base[point.label] ?? 0.5) - 0.5) * point.score);
  };
  return [
    {
      stage: "شروع",
      مشتری: pointValence(profile.caller.start),
      اپراتور: profile.agent ? pointValence(profile.agent.start) : undefined,
    },
    {
      stage: "میانگین",
      مشتری: pointValence(profile.caller.overall),
      اپراتور: profile.agent ? pointValence(profile.agent.overall) : undefined,
    },
    {
      stage: "پایان",
      مشتری: pointValence(profile.caller.end),
      اپراتور: profile.agent ? pointValence(profile.agent.end) : undefined,
    },
  ];
}

const EVENT_KIND_LABELS: Record<ProcessingEvent["kind"], string> = {
  pipeline: "آماده‌سازی",
  asr: "تبدیل گفتار",
  emotion: "تحلیل لحن صدا",
  correction: "تصحیح هوشمند متن",
  llm: "تحلیل هوشمند",
  notify: "اطلاع‌رسانی",
};

function eventState(event: ProcessingEvent) {
  if (event.level === "error" || event.status === "failed_terminal") {
    return { label: "ناموفق", icon: "×", tone: "text-rose-600 bg-rose-50" };
  }
  if (event.level === "warning" || event.status === "failed_retryable") {
    return { label: "خطا؛ تلاش مجدد", icon: "!", tone: "text-amber-700 bg-amber-50" };
  }
  if (event.status === "canceled") {
    return { label: "لغو شد", icon: "×", tone: "text-slate-500 bg-slate-100" };
  }
  if (event.level === "success" || (event.status && event.status !== "queued" && event.status !== "running")) {
    return { label: "انجام شد", icon: "✓", tone: "text-emerald-700 bg-emerald-50" };
  }
  if (event.status === "queued") {
    return { label: "در صف", icon: "◷", tone: "text-slate-500 bg-slate-100" };
  }
  return { label: "در حال انجام", icon: "↻", tone: "text-blue-700 bg-blue-50" };
}

function ProcessingTimeline({ events }: { events: ProcessingEvent[] }) {
  if (!events.length) return null;

  return (
    <details className="card group" dir="rtl">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 [&::-webkit-details-marker]:hidden">
        <span className="text-sm font-bold text-slate-800">گزارش اجرای پردازش</span>
        <span className="flex h-9 w-9 items-center justify-center border border-[color:var(--line)] bg-[#F2F0EF] text-[#000000] transition-transform duration-200 group-open:rotate-180" aria-hidden="true">
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </span>
      </summary>
      <div className="mt-4 max-h-[32rem] overflow-y-auto overscroll-contain sm:max-h-[42rem]">
        <ol className="divide-y divide-slate-100" dir="rtl">
          {events.map((event) => {
            const state = eventState(event);
            return (
              <li key={event.id} className="py-2.5 first:pt-0 last:pb-0">
                <div className="flex items-start gap-3">
                  <span className={`flex h-7 w-7 shrink-0 items-center justify-center text-base font-bold leading-none ${state.tone}`} aria-hidden="true">
                    {state.icon}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
                      <span className="font-semibold text-slate-700">{EVENT_KIND_LABELS[event.kind]}</span>
                      <span className="text-slate-600">{event.message}</span>
                      <span className="text-[11px] font-medium text-slate-500">{state.label}</span>
                      <time className="mr-auto text-[10px] text-slate-400" dateTime={event.created_at}>
                        {fmt.dateTime(event.created_at)}
                      </time>
                    </div>
                    {event.error_code || event.error_detail ? (
                      <details className="mt-1.5 text-[11px] text-rose-700">
                        <summary className="w-fit cursor-pointer font-medium hover:text-rose-900">
                          {event.error_code ? <span>کد خطا: <bdi>{event.error_code}</bdi></span> : "جزئیات خطا"}
                        </summary>
                        {event.error_detail ? (
                          <div className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-rose-50 p-2.5 leading-5" dir="auto">
                            {event.error_detail}
                          </div>
                        ) : null}
                      </details>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </div>
    </details>
  );
}

interface MenuAction { label: string; onClick: () => void; disabled?: boolean }

/** "More" menu: keeps rarely used actions and technical details out of the card header. */
function OverflowMenu({ label, actions, details }: { label: string; actions: MenuAction[]; details?: Array<{ term: string; value: string; ltr?: boolean }> }) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  // Portalled and fixed so neighbouring stacking contexts (the title band, the message bubbles) cannot cover or clip it.
  useLayoutEffect(() => {
    if (!open) { setPosition(null); return; }
    const place = () => {
      const trigger = triggerRef.current;
      const menu = menuRef.current;
      if (!trigger || !menu) return;
      const anchor = trigger.getBoundingClientRect();
      const margin = 8;
      const left = Math.min(Math.max(anchor.left, margin), Math.max(window.innerWidth - menu.offsetWidth - margin, margin));
      setPosition({ top: anchor.bottom + 4, left });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); triggerRef.current?.focus(); } };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("pointerdown", onPointerDown); document.removeEventListener("keydown", onKeyDown); };
  }, [open]);
  return (
    <>
      <button ref={triggerRef} type="button" className={`flex h-9 w-9 items-center justify-center border border-[#898989] text-[#4B6E48] hover:bg-[#F2F0EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] ${open ? "bg-[#F2F0EF]" : "bg-white"}`} aria-haspopup="menu" aria-expanded={open} aria-label={label} title={label} onClick={() => setOpen((current) => !current)}>
        <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
      </button>
      {open ? createPortal(
        <div ref={menuRef} role="menu" dir="rtl" className="fixed z-50 w-64 max-w-[calc(100vw-1rem)] border border-[color:var(--line)] bg-[#F2F0EF] py-1 shadow-lg" style={{ top: position?.top ?? 0, left: position?.left ?? 0, visibility: position ? "visible" : "hidden" }}>
          {actions.map((action) => (
            <button key={action.label} type="button" role="menuitem" className="block w-full px-3 py-2 text-start text-sm text-slate-700 hover:bg-white hover:text-[#4B6E48] focus-visible:bg-white focus-visible:outline-none disabled:cursor-not-allowed disabled:text-[#898989] disabled:hover:bg-transparent" disabled={action.disabled} onClick={() => { setOpen(false); action.onClick(); }}>
              {action.label}
            </button>
          ))}
          {details?.length ? (
            <dl className="mt-1 space-y-1 border-t border-[color:var(--line)] px-3 py-2 text-[11px] text-slate-500">
              {details.map((item) => (
                <div key={item.term} className="flex justify-between gap-3"><dt>{item.term}</dt><dd className="min-w-0 truncate text-slate-700" dir={item.ltr ? "ltr" : undefined}>{item.value}</dd></div>
              ))}
            </dl>
          ) : null}
        </div>,
        document.body,
      ) : null}
    </>
  );
}

export default function CallDetailPage() {
  const { callId } = useParams<{ callId: string }>();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const transcriptView = searchParams.get("transcript") === "raw" ? "raw" : "final";
  const selectedTranscriptVersion = searchParams.get("transcriptVersion");
  const { session } = useAuth();
  const [call, setCall] = useState<CallDetail | null>(null);
  const [transcriptVersions, setTranscriptVersions] = useState<AsrTranscriptRevision[]>([]);
  const [operatorScore, setOperatorScore] = useState<OperatorScore | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [sentimentSource, setSentimentSource] = useState<"text" | "voice">("voice");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioLoading, setAudioLoading] = useState(false);
  const [audioProgress, setAudioProgress] = useState<number | null>(0);
  const [audioStage, setAudioStage] = useState<"downloading" | "extracting">("downloading");
  const [correctionLoading, setCorrectionLoading] = useState(false);
  const [processingActionLoading, setProcessingActionLoading] = useState(false);
  const [correctionFeedback, setCorrectionFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(null);
  const [copiedTurnId, setCopiedTurnId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirmationOpen, setDeleteConfirmationOpen] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl]);

  useEffect(() => {
    setAudioUrl(null);
    setAudioLoading(false);
    setAudioProgress(0);
    setAudioStage("downloading");
    audioRef.current?.pause();
    audioRef.current?.removeAttribute("src");
  }, [callId]);

  useEffect(() => {
    let cancelled = false;
    let processing = true;
    let hasCall = false;

    async function load() {
      try {
        const data = await request<CallDetail>(`/v1/calls/${callId}`);
        if (cancelled) return;
        hasCall = true;
        setCall(data);
        const hasAudioAnalysis = data.call_type === "answered" || data.call_type === "voicemail";
        const versions = !hasAudioAnalysis ? [] : await request<AsrTranscriptRevision[]>(`/v1/calls/${callId}/transcript-versions`).catch(() => []);
        if (cancelled) return;
        setTranscriptVersions(versions);
        if (data.call_type !== "answered") setOperatorScore(null);
        else void request<OperatorScore | null>(`/v1/calls/${callId}/operator-score`).then(setOperatorScore).catch(() => setOperatorScore(null));
        setError(null);
        processing = hasAudioAnalysis && (data.processing
          || ["queued", "running", "validating"].includes(data.correction?.status ?? "")
          || versions.some((item) => ["queued", "running"].includes(item.status)));
      } catch (err) {
        if (!cancelled && !hasCall) setError((err as Error).message);
      }
    }

    void load();
    const timer = window.setInterval(() => {
      if (processing) void load();
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [callId, reload]);

  async function playAudio() {
    if (audioUrl) {
      try {
        await audioRef.current?.play();
      } catch {
        setError("پخش خودکار ممکن نشد؛ از کنترل پخش زیر استفاده کنید.");
      }
      return;
    }
    setAudioLoading(true);
    setAudioProgress(0);
    setAudioStage("downloading");
    setError(null);
    let awaitingWaveform = false;
    try {
      const fetchAudio = () => fetch(`/v1/calls/${callId}/audio/content`, {
        headers: { Authorization: `Bearer ${tokens.access() ?? ""}` },
      });
      let response = await fetchAudio();
      if (response.status === 401 && await refreshSession()) response = await fetchAudio();
      if (response.status === 404) {
        setCall((current) => current ? { ...current, audio_available: false } : current);
        return;
      }
      if (!response.ok) throw new Error("دریافت فایل صوتی ممکن نبود");
      const contentLength = Number(response.headers.get("content-length"));
      let blob: Blob;
      if (response.body) {
        const reader = response.body.getReader();
        const chunks: Uint8Array[] = [];
        let receivedBytes = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          receivedBytes += value.byteLength;
          setAudioProgress(
            Number.isFinite(contentLength) && contentLength > 0
              ? Math.min(100, Math.round((receivedBytes / contentLength) * 100))
              : null,
          );
        }
        blob = new Blob(chunks, { type: response.headers.get("content-type") ?? "audio/wav" });
      } else {
        setAudioProgress(null);
        blob = await response.blob();
      }
      if (!blob.size) throw new Error("فایل صوتی خالی است");
      const url = URL.createObjectURL(blob);
      awaitingWaveform = true;
      setAudioStage("extracting");
      setAudioProgress(null);
      setAudioUrl(url);
      if (audioRef.current) {
        audioRef.current.src = url;
        try {
          await audioRef.current.play();
        } catch {
          // Controls remain visible if the browser blocks playback after the async download.
        }
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      if (!awaitingWaveform) setAudioLoading(false);
    }
  }

  const handleWaveformReady = useCallback(() => {
    setAudioProgress(100);
    setAudioLoading(false);
  }, []);

  async function reanalyze() {
    if (!call?.transcript) {
      setError("متن تماس هنوز آماده نشده است؛ پس از اتمام تبدیل صوت به متن دوباره تلاش کنید.");
      return;
    }
    setProcessingActionLoading(true);
    setError(null);
    try {
      await request<void>(`/v1/calls/${callId}/reanalyze`, { method: "POST" });
      setNotice("درخواست تحلیل مجدد ثبت شد (بدون هزینه اضافه).");
      setReload((value) => value + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProcessingActionLoading(false);
    }
  }

  async function retryTranscription() {
    if (!call?.can_retry_transcription) return;
    setProcessingActionLoading(true);
    setError(null);
    try {
      await request<void>(`/v1/calls/${callId}/retry-transcription`, { method: "POST" });
      setNotice("پردازش مجدد صوت در صف قرار گرفت.");
      setReload((value) => value + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProcessingActionLoading(false);
    }
  }

  async function retranscribe() {
    setProcessingActionLoading(true);
    setError(null);
    try {
      await request(`/v1/calls/${callId}/retranscribe`, { method: "POST" });
      setNotice("ساخت نسخه جدید متن بدون کسر اعتبار در صف قرار گرفت.");
      setReload((value) => value + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProcessingActionLoading(false);
    }
  }

  async function activateTranscriptVersion(revisionId: string) {
    setProcessingActionLoading(true);
    setError(null);
    try {
      await request(`/v1/calls/${callId}/transcript-versions/${revisionId}/activate`, { method: "POST" });
      const next = new URLSearchParams(searchParams);
      next.set("transcriptVersion", revisionId);
      setSearchParams(next, { replace: true });
      setNotice("نسخه انتخاب‌شده فعال و تحلیل مجدد در صف قرار گرفت.");
      setReload((value) => value + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setProcessingActionLoading(false);
    }
  }

  async function deleteCall() {
    setDeleting(true);
    setError(null);
    try {
      await request<void>(`/v1/calls/${callId}`, { method: "DELETE" });
      setDeleteConfirmationOpen(false);
      navigate("/calls", { replace: true });
    } catch (err) {
      setError((err as Error).message);
      setDeleting(false);
    }
  }

  async function correctTranscript() {
    setCorrectionLoading(true);
    setError(null);
    setCorrectionFeedback(null);
    try {
      const result = await request<{ correction_run_id: string; status: CorrectionStatus["status"] }>(`/v1/calls/${callId}/correct-transcript`, { method: "POST" });
      const message = ["queued", "running", "validating"].includes(result.status)
        ? "درخواست تصحیح ثبت شد و در حال پردازش است."
        : "تصحیح متن با موفقیت انجام شد.";
      setCorrectionFeedback({ tone: "success", message });
      setCall((current) => current ? {
        ...current,
        correction: {
          id: result.correction_run_id,
          status: result.status,
          trigger: "manual",
          mode: current.correction?.mode ?? "text_only",
          audio_models: current.correction?.audio_models ?? [],
          text_models: current.correction?.text_models ?? [],
          provider_model: null,
          error_code: null,
          error_detail: null,
          uncertain_items: [],
          uncertain_count: 0,
          uncertain_ratio: 0,
          queued_at: new Date().toISOString(),
          started_at: null,
          provider_submitted_at: null,
          completed_at: null,
        },
      } : current);
      setReload((value) => value + 1);
    } catch (err) {
      setCorrectionFeedback({ tone: "error", message: (err as Error).message });
    } finally {
      setCorrectionLoading(false);
    }
  }

  async function copyTranscriptTurn(turnId: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedTurnId(turnId);
      window.setTimeout(() => setCopiedTurnId((current) => current === turnId ? null : current), 1600);
    } catch {
      setError("کپی پیام انجام نشد.");
    }
  }

  if (error && !call) return <ErrorBox message={error} />;
  if (!call) return <CallDetailSkeleton />;

  const insights = call.insights;
  const tasks: FollowUpTask[] = [...(Array.isArray(call.tasks) ? call.tasks : [])].sort((left, right) => {
    if (left.status === right.status) return left.created_at.localeCompare(right.created_at);
    return left.status === "open" ? -1 : 1;
  });
  const canEditTasks = Boolean(session && CAN_EDIT_TASKS.includes(session.role));
  const correctionActive = ["queued", "running", "validating"].includes(call.correction?.status ?? "");
  const correctionButtonLabel = correctionLoading || correctionActive
    ? call.correction?.status === "validating"
      ? "در حال اعتبارسنجی…"
      : call.correction?.status === "queued"
        ? "تصحیح در صف…"
        : "در حال تصحیح…"
    : call.corrected_transcript
      ? "تصحیح دوباره متن"
      : "تصحیح متن";
  const selectedRevision = transcriptVersions.find((item) => item.id === selectedTranscriptVersion);
  const displayRevision = selectedRevision ?? transcriptVersions.find((item) => item.active);
  const visibleUtterances = selectedRevision && !selectedRevision.active
    ? transcriptView === "final" && selectedRevision.corrected_utterances.length
      ? selectedRevision.corrected_utterances
      : selectedRevision.utterances
    : transcriptView === "raw" ? call.raw_utterances : call.utterances;
  const speakerLabels = (selectedRevision?.speaker_mode ?? call.speaker_mode)?.startsWith("mono")
    ? { 0: "گوینده ۱", 1: "گوینده ۲" }
    : call.speaker_labels;
  const conversationTurns = buildConversationTurns(visibleUtterances);
  const callerDuration = conversationTurns
    .filter((turn) => turn.channel === 0)
    .reduce((total, turn) => total + Math.max(0, turn.t_end_ms - turn.t_start_ms), 0);
  const agentDuration = conversationTurns
    .filter((turn) => turn.channel !== 0)
    .reduce((total, turn) => total + Math.max(0, turn.t_end_ms - turn.t_start_ms), 0);
  const totalSpeechDuration = callerDuration + agentDuration;
  const coveredSpeechDuration = intervalUnionDuration(conversationTurns);
  const speechCoverage = call.duration_ms
    ? Math.min(100, Math.round((coveredSpeechDuration / call.duration_ms) * 100))
    : 0;
  const averageTurnDuration = conversationTurns.length
    ? Math.round(totalSpeechDuration / conversationTurns.length)
    : 0;
  const speakerData = [
    { name: speakerLabels[0] ?? "گوینده ۱", value: callerDuration },
    { name: speakerLabels[1] ?? "گوینده ۲", value: agentDuration },
  ].filter((item) => item.value > 0);
  const activeSentimentProfile =
    sentimentSource === "voice"
      ? (insights?.sentiment_profile?.voice ?? insights?.sentiment_profile?.text)
      : (insights?.sentiment_profile?.text ?? insights?.sentiment_profile?.voice);
  const sentimentData = sentimentChartData(activeSentimentProfile);
  const sentimentScore = insights?.sentiment_score;
  const hasAudioAnalysis = call.call_type === "answered" || call.call_type === "voicemail";
  const isAnsweredCall = call.call_type === "answered";
  const callFailed = call.status.startsWith("failed");
  const stateKind: CallStateKind = call.processing ? "processing" : callFailed ? "failed" : "empty";
  const isVoicemail = call.call_type === "voicemail";
  const isQuickDemo = isVoicemail && call.voicemail_context === "quick_demo";
  const isMissedCall = ["missed", "no_answer", "busy", "congestion", "failed", "canceled"].includes(call.call_type);

  const exportTranscript = () => {
    if (!conversationTurns.length) return;
    const transcript = conversationTurns.map((turn) => {
      const speaker = speakerLabels[turn.channel] ?? `کانال ${fmt.int(turn.channel + 1)}`;
      return `${speaker} (${fmt.duration(turn.t_start_ms)} تا ${fmt.duration(turn.t_end_ms)})\n${turn.text}`;
    }).join("\n\n--------------------\n\n");
    const heading = [
      "متن مکالمه تماس",
      `تاریخ تماس: ${fmt.dateTime(call.started_at)}`,
      `مدت تماس: ${fmt.duration(call.duration_ms)}`,
      `شماره تماس‌گیرنده: ${call.caller_number ? fmt.digits(call.caller_number) : "—"}${call.caller_name ? ` (${call.caller_name})` : ""}`,
      `شماره مقصد: ${call.dialed_number ? fmt.digits(call.dialed_number) : "—"}${call.dialed_name ? ` (${call.dialed_name})` : ""}`,
    ].join("\n");
    downloadTextFile(`call-${call.id}-transcript.txt`, `${heading}\n\n${transcript}\n`);
  };

  return (
    <div className="space-y-5">
      <ErrorBox message={error} />

      {call.recovery_pending ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="status">
          ارسال تحلیل با تأخیر روبه‌رو شده است؛ بازیابی خودکار فعال است و نیازی به ثبت تحلیل مجدد نیست.
        </div>
      ) : null}

      <section className="call-detail-hero card relative overflow-visible !p-0">
        <div className="absolute inset-x-0 top-0 h-1 bg-[#4B6E48]" />
        <div className="relative p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs text-[#000000]">
              <Link className="transition hover:text-[#000000]" to="/calls">تماس‌ها</Link>
              <span>/</span>
              <span className="font-medium text-[#000000]">جزئیات و تحلیل تماس</span>
            </div>
            <div className="call-header-status flex flex-wrap items-center gap-2">
              <StatusBadge status={hasAudioAnalysis ? call.status : call.call_type} />
              <span className="bg-[#B2AC88] px-2.5 py-1 text-[11px] text-[#000000]">
                شناسه {fmt.digits(call.id.slice(0, 8))}
              </span>
            </div>
          </div>

          <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
            <div>
              <div className="mb-2 flex items-center gap-3">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center bg-[#F2F0EF] text-[#000000]" aria-hidden="true">
                  <Icon icon={telephoneIcon} className="h-8 w-8" />
                </span>
                <div>
                  <p className="text-xs text-[#000000]">{isQuickDemo ? "تست سریع صداسنج" : isVoicemail ? "پیام‌گیر صوتی" : isMissedCall ? "تماس ناموفق" : "مکالمه تلفنی"}</p>
                  <h1 className="mt-0.5 inline-flex items-center gap-1 text-xl font-extrabold text-[#000000] sm:text-2xl" dir="rtl">
                    <CallParty number={call.caller_number} name={call.caller_name} />
                    <span className="px-1 text-[#B2AC88]">
                      <span aria-hidden="true">←</span>
                      <span className="sr-only">به</span>
                    </span>
                    <CallParty number={call.dialed_number} name={call.dialed_name} />
                  </h1>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-[#000000]">
                <span>تاریخ تماس: {fmt.dateTime(call.started_at)}</span>
                <span>مدت: {fmt.duration(call.duration_ms)}</span>
                {call.direction ? <span>جهت: {DIRECTION_LABELS[call.direction] ?? call.direction}</span> : null}
                {call.agent_extension ? <span>داخلی: {fmt.digits(call.agent_extension)}</span> : null}
                {call.call_type === "voicemail" && call.voicemail_folder ? <span>پوشهٔ صندوق: {call.voicemail_folder}</span> : null}
                {call.call_type === "voicemail" && call.voicemail_context ? <span>بافت صندوق: {call.voicemail_context}</span> : null}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ActionTooltip label="بازگشت به تماس‌ها">
                <Link className={CALL_ACTION_CLASS} to="/calls" aria-label="بازگشت به تماس‌ها">
                  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                </Link>
              </ActionTooltip>
              {session && CAN_HEAR_AUDIO.includes(session.role) && call.audio_available ? (
                <ActionTooltip label={audioLoading ? (audioStage === "extracting" ? "در حال استخراج موج صدا…" : "در حال دریافت صوت…") : "پخش فایل صوتی"}>
                  <button
                    type="button"
                    className={CALL_ACTION_CLASS}
                    onClick={() => void playAudio()}
                    disabled={audioLoading}
                    aria-label={audioLoading ? (audioStage === "extracting" ? "در حال استخراج موج صدا" : `در حال دریافت صوت${audioProgress === null ? "" : `، ${audioProgress} درصد`}`) : "پخش فایل صوتی"}
                  >
                    {audioLoading ? (
                      <CircularAudioProgress progress={audioProgress} />
                    ) : (
                      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                        <path d="M5 9v6h4l5 4V5L9 9H5Z" />
                        <path d="M18 9a4 4 0 0 1 0 6M20.5 6.5a8 8 0 0 1 0 11" />
                      </svg>
                    )}
                  </button>
                </ActionTooltip>
              ) : null}
              {(call.call_type === "answered" && (session?.role === "org_admin" || session?.role === "operator") || call.call_type === "voicemail" && session?.role === "org_admin") ? (
                <ActionTooltip label="پرسش درباره این تماس">
                  <Link className={CALL_ACTION_CLASS} to={`/assistant?call_id=${call.id}`} aria-label="پرسش درباره این تماس">
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                      <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v8Z" />
                      <path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.7M12 16h.01" />
                    </svg>
                  </Link>
                </ActionTooltip>
              ) : null}
              {session?.role === "org_admin" || session?.role === "operator" ? (
                <ActionTooltip label={
                  processingActionLoading
                    ? "در حال ثبت درخواست…"
                    : call.transcript
                      ? "تحلیل مجدد"
                      : call.can_retry_transcription
                        ? "پردازش مجدد صوت"
                        : "پس از آماده‌شدن متن تماس، تحلیل مجدد فعال می‌شود"
                }>
                  <button
                    type="button"
                    className={CALL_ACTION_CLASS}
                    onClick={() => void (call.transcript ? reanalyze() : retryTranscription())}
                    disabled={processingActionLoading || (!call.transcript && !call.can_retry_transcription)}
                    aria-label={call.transcript ? "تحلیل مجدد" : "پردازش مجدد صوت"}
                  >
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                      <path d="M20 7v5h-5M4 17v-5h5" />
                      <path d="M6.1 9A7 7 0 0 1 18.7 6.7L20 12M4 12l1.3 5.3A7 7 0 0 0 17.9 15" />
                    </svg>
                  </button>
                </ActionTooltip>
              ) : null}
              {isOrgAdmin(session?.role) ? (
                <ActionTooltip label={deleting ? "در حال حذف…" : "حذف تماس"}>
                  <button type="button" className={CALL_ACTION_CLASS} disabled={deleting} onClick={() => setDeleteConfirmationOpen(true)} aria-label="حذف تماس">
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                      <path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" />
                    </svg>
                  </button>
                </ActionTooltip>
              ) : null}
            </div>
          </div>
          {audioUrl ? (
            <div className="mt-5 border-t border-[color:var(--line)] pt-4">
              <AudioWaveformPlayer
                audioRef={audioRef}
                downloadName={`call-${call.id}-audio`}
                src={audioUrl}
                onError={() => setError("مرورگر قادر به پخش این فایل صوتی نیست.")}
                onWaveformReady={handleWaveformReady}
              />
            </div>
          ) : null}
        </div>
      </section>

      {notice ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{notice}</div>
      ) : null}

      {!hasAudioAnalysis ? isMissedCall ? null : <section className="card border-rose-100 bg-rose-50/50"><h2 className="font-bold text-rose-800">نوع تماس: {STATUS_LABELS[call.call_type] ?? call.call_type}</h2><p className="mt-1 text-sm text-slate-600">برای این رخداد فایل صوتی یا تحلیل مکالمه ثبت نشده است.</p></section> : <ProcessingCard status={call.status} progressPct={call.progress_pct} detail={call.progress_detail} />}

      {isMissedCall ? (
        <section className="card border-amber-200 bg-amber-50/60">
          <h2 className="font-bold text-amber-900">جزئیات تماس ناموفق</h2>
          <p className="mt-1 text-sm leading-6 text-amber-800">
            {STATUS_LABELS[call.call_type] ?? call.call_type} — این تماس پاسخ داده نشده و فایل صوتی یا گفت‌وگویی برای تحلیل ندارد.
          </p>
          {call.error_code || call.error_detail ? <div className="mt-3 border-t border-amber-200 pt-3 text-xs leading-6 text-amber-900">{call.error_code ? <strong dir="ltr">{call.error_code}</strong> : null}{call.error_code && call.error_detail ? " — " : ""}{call.error_detail}</div> : null}
        </section>
      ) : null}

      {call.status.startsWith("failed") && (call.error_code || call.error_detail) ? (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-4 text-rose-800">
          <h2 className="text-sm font-bold">علت توقف پردازش</h2>
          {call.error_code ? <p className="mt-1 text-xs font-semibold">کد خطا: {call.error_code}</p> : null}
          {call.error_detail ? <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-6" dir="auto">{call.error_detail}</p> : null}
        </section>
      ) : null}

      {hasAudioAnalysis ? <ProcessingTimeline events={call.processing_events ?? []} /> : null}

      {hasAudioAnalysis ? <section className="card overflow-visible">
        <SectionTitle
          title="کارهای قابل پیگیری"
          description="موارد عملیاتی استخراج‌شده از تماس؛ می‌توانید آن‌ها را ویرایش یا انجام‌شده کنید"
          action={
            <Link className="btn-ghost inline-flex h-9 items-center px-3 py-0 text-xs" to="/tasks">
              همه کارها
            </Link>
          }
        />
        {tasks.length === 0 ? (
          <EmptyState icon="tasks" compact message="موردی ثبت نشده است." className="min-h-36" />
        ) : (
          <ul className="space-y-2">
            {tasks.map((task) => (
              <FollowUpTaskCard
                key={task.id}
                task={task}
                canEdit={canEditTasks}
                showCallLink={false}
                onUpdated={(next) =>
                  setCall((current) =>
                    current
                      ? {
                          ...current,
                          tasks: current.tasks.map((item) => (item.id === next.id ? next : item)),
                        }
                      : current,
                  )
                }
              />
            ))}
          </ul>
        )}
      </section> : null}

      {hasAudioAnalysis ? (
      <div className="card">
        <SectionTitle title="خلاصه هوشمند" description="چکیده محتوای تماس" />
        {insights?.summary ? (
          <p className="text-sm leading-7 text-slate-700">{insights.summary}</p>
        ) : (
          <EmptyState
            icon="summary" compact
            state={stateKind}
            message={call.processing ? "خلاصه در حال آماده‌سازی است…" : callFailed ? "خلاصه تولید نشد. تحلیل مجدد را اجرا کنید." : "خلاصه‌ای برای این تماس ثبت نشده است."}
            className="min-h-32"
          />
        )}
        {insights?.keywords?.length ? (
          <div className="mt-4 flex flex-wrap gap-1.5 border-t border-slate-100 pt-4">
            {insights.keywords.map((keyword) => (
              <span key={keyword} className="badge bg-brand-50 px-2.5 py-1 text-brand-700"># {keyword}</span>
            ))}
          </div>
        ) : null}
      </div>
      ) : null}

      {hasAudioAnalysis && isAnsweredCall ? <OperatorCoachSection callId={call.id} canRegenerate={canEditTasks} internal={call.direction === "internal"} /> : null}

      {isAnsweredCall ? <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="مدت کل تماس" value={fmt.duration(call.duration_ms)} hint="از شروع تا پایان مکالمه" icon={<Icon icon={alarmClockIcon} className="h-9 w-9 text-[#4B6E48]" />} />
        <MetricCard
          label="نوبت‌های گفت‌وگو"
          value={fmt.int(conversationTurns.length)}
          hint={`میانگین هر نوبت ${fmt.duration(averageTurnDuration)}`}
          icon={<Icon icon={repeatButtonIcon} className="h-9 w-9 text-[#4B6E48]" />}
        />
        <MetricCard
          label="پوشش گفتار"
          value={fmt.percent(speechCoverage)}
          hint="نسبت گفتار تشخیص‌داده‌شده به تماس"
          icon={<Icon icon={barChartIcon} className="h-9 w-9 text-[#4B6E48]" />}
        />
        <MetricCard
          label="امتیاز احساس"
          value={sentimentScore == null ? "—" : fmt.percent(sentimentScore * 100)}
          hint={insights?.intent ? (INTENT_LABELS[insights.intent] ?? insights.intent) : "قصد تماس نامشخص"}
          icon={<Icon icon={bullseyeIcon} className="h-9 w-9 text-[#4B6E48]" />}
        />
        <MetricCard label="امتیاز عملکرد" value={operatorScore?.total_score == null ? "—" : fmt.decimal(operatorScore.total_score)} hint={operatorScore?.status === "succeeded" ? operatorScore.operator_label : "در حال ارزیابی"} icon={<Icon icon={starIcon} className="h-9 w-9 text-[#4B6E48]" />} />
      </section> : isVoicemail ? <section className="grid gap-3 sm:grid-cols-2">
        <MetricCard label="مدت پیام" value={fmt.duration(call.duration_ms)} hint="مدت فایل پیام‌گیر صوتی" icon={<Icon icon={alarmClockIcon} className="h-9 w-9 text-[#4B6E48]" />} />
        <MetricCard label="بخش‌های پیاده‌سازی‌شده" value={fmt.int(conversationTurns.length)} hint="تعداد بخش‌های متن پیام" icon={<Icon icon={barChartIcon} className="h-9 w-9 text-[#4B6E48]" />} />
      </section> : null}

      {isAnsweredCall && operatorScore?.criteria_scores?.length ? <section className="card"><SectionTitle title="ارزیابی عملکرد اپراتور" description={operatorScore.operator_label} /><div className="grid gap-3 md:grid-cols-2">{operatorScore.criteria_scores.map((criterion) => <div key={criterion.title} className="rounded-xl border border-slate-200 p-3"><div className="flex justify-between"><strong>{criterion.title}</strong><span>{fmt.decimal(criterion.score)}</span></div>{criterion.evidence ? <p className="mt-2 text-sm text-slate-600">{criterion.evidence}</p> : null}</div>)}</div></section> : null}

      {isAnsweredCall ? <section className="grid gap-4 xl:grid-cols-5">
        <div className="card xl:col-span-3">
          <SectionTitle
            title="روند احساس مکالمه"
            description="مقایسه تغییر امتیاز احساس مشتری و اپراتور در طول تماس"
            action={
              insights?.sentiment_profile?.voice ? (
                <div className="flex rounded-lg bg-slate-100 p-1 text-xs">
                  <button
                    className={`rounded-md px-3 py-1.5 transition ${sentimentSource === "text" ? "bg-white font-semibold text-brand-700 shadow-sm" : "text-slate-500"}`}
                    onClick={() => setSentimentSource("text")}
                  >
                    تحلیل متن
                  </button>
                  <button
                    className={`rounded-md px-3 py-1.5 transition ${sentimentSource === "voice" ? "bg-white font-semibold text-brand-700 shadow-sm" : "text-slate-500"}`}
                    onClick={() => setSentimentSource("voice")}
                  >
                    تحلیل صدا
                  </button>
                </div>
              ) : undefined
            }
          />
          {sentimentData.length ? (
            <>
              <div className="h-64" dir="ltr">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={sentimentData} margin={{ top: 8, right: 10, left: -12, bottom: 0 }}>
                    <defs>
                      <linearGradient id="callerLine" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor={chart.primary} />
                        <stop offset="100%" stopColor={chart.secondary} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={chart.light} strokeDasharray="4 6" vertical={false} />
                    <XAxis dataKey="stage" axisLine={false} tickLine={false} tick={{ fill: chart.neutral, fontSize: 12 }} />
                    <YAxis
                      domain={[0, 100]}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: chart.neutral, fontSize: 11 }}
                      tickFormatter={fmt.int}
                    />
                    <Tooltip
                      formatter={(value) => fmt.percent(Number(value))}
                      contentStyle={{ borderRadius: 0, borderColor: chart.light, direction: "rtl", fontFamily: "Vazirmatn" }}
                    />
                    <Legend wrapperStyle={{ direction: "rtl", fontSize: 12 }} />
                    <Line type="monotone" dataKey="مشتری" stroke="url(#callerLine)" strokeWidth={3} dot={{ r: 5, fill: chart.primary, strokeWidth: 3, stroke: palette.canvas }} activeDot={{ r: 7 }} connectNulls />
                    <Line type="monotone" dataKey="اپراتور" stroke={chart.secondary} strokeWidth={3} dot={{ r: 5, fill: chart.secondary, strokeWidth: 3, stroke: palette.canvas }} activeDot={{ r: 7 }} connectNulls />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-3 grid gap-2 border-t border-slate-100 pt-4 sm:grid-cols-2">
                <div className="flex items-center justify-between rounded-xl bg-brand-50/70 px-3 py-2.5">
                  <span className="text-xs font-semibold text-slate-600">احساس مشتری</span>
                  <span className="flex items-center gap-2">
                    <SentimentBadge sentiment={activeSentimentProfile?.caller.overall.label ?? null} />
                    <TrajectoryBadge trajectory={activeSentimentProfile?.caller.trajectory} />
                  </span>
                </div>
                <div className="flex items-center justify-between rounded-xl bg-violet-50/70 px-3 py-2.5">
                  <span className="text-xs font-semibold text-slate-600">احساس اپراتور</span>
                  <span className="flex items-center gap-2">
                    <SentimentBadge sentiment={activeSentimentProfile?.agent?.overall.label ?? null} />
                    <TrajectoryBadge trajectory={activeSentimentProfile?.agent?.trajectory} />
                  </span>
                </div>
              </div>
            </>
          ) : (
            <EmptyState icon="sentiment" state={stateKind} message={call.processing ? "تحلیل احساس در حال انجام است…" : callFailed ? "تحلیل احساس کامل نشد. تحلیل مجدد را اجرا کنید." : "هنوز داده کافی برای ترسیم روند احساس وجود ندارد."} className="h-64" />
          )}
        </div>

        <div className="card xl:col-span-2">
          <SectionTitle title="سهم مکالمه" description="توزیع زمان گفتار تشخیص‌داده‌شده بین دو طرف" />
          {speakerData.length ? (
            <>
              <div className="relative h-64" dir="ltr">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={speakerData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={66} outerRadius={94} paddingAngle={4} stroke="none">
                      {speakerData.map((item, index) => (
                        <Cell key={item.name} fill={SPEAKER_COLORS[index % SPEAKER_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value) => fmt.duration(Number(value))}
                      contentStyle={{ borderRadius: 0, borderColor: chart.light, direction: "rtl", fontFamily: "Vazirmatn" }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center" dir="rtl">
                  <span className="text-2xl font-extrabold text-slate-800">{fmt.duration(totalSpeechDuration)}</span>
                  <span className="text-[11px] text-slate-400">گفتار مفید</span>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {speakerData.map((item, index) => (
                  <div key={item.name} className="rounded-xl border border-slate-100 bg-slate-50 p-3">
                    <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: SPEAKER_COLORS[index % SPEAKER_COLORS.length] }} />
                      {item.name}
                    </div>
                    <div className="font-bold text-slate-700">{fmt.duration(item.value)}</div>
                    <div className="mt-0.5 text-[10px] text-slate-400">
                      {fmt.percent(totalSpeechDuration ? (item.value / totalSpeechDuration) * 100 : 0)} از گفتار
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <EmptyState icon="conversation" state={stateKind} message={call.processing ? "سهم گفتار پس از پیاده‌سازی محاسبه می‌شود…" : callFailed ? "داده گفتاری تولید نشد. رونویسی مجدد را اجرا کنید." : "داده گفتاری برای این تماس ثبت نشده است."} className="h-64" />
          )}
        </div>
      </section> : null}

      {isAnsweredCall && conversationTurns.length ? (
        <section className="card">
          <SectionTitle title="ریتم مکالمه" description="مدت هر نوبت گفت‌وگو در ترتیب زمانی تماس" />
          <div className="h-52" dir="ltr">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={conversationTurns.slice(0, 30).map((turn, index) => ({
                  turn: fmt.int(index + 1),
                  مشتری: turn.channel === 0 ? Math.max(0, turn.t_end_ms - turn.t_start_ms) / 1000 : 0,
                  اپراتور: turn.channel !== 0 ? Math.max(0, turn.t_end_ms - turn.t_start_ms) / 1000 : 0,
                }))}
                margin={{ top: 4, right: 10, left: -12, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="callerArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={chart.primary} stopOpacity={0.45} />
                    <stop offset="100%" stopColor={chart.primary} stopOpacity={0.03} />
                  </linearGradient>
                  <linearGradient id="agentArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={chart.secondary} stopOpacity={0.4} />
                    <stop offset="100%" stopColor={chart.secondary} stopOpacity={0.03} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={chart.light} strokeDasharray="4 6" vertical={false} />
                <XAxis dataKey="turn" axisLine={false} tickLine={false} tick={{ fill: chart.neutral, fontSize: 10 }} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: chart.neutral, fontSize: 10 }}
                  tickFormatter={(value) => fmt.decimal(Number(value))}
                  unit=" ث"
                />
                <Tooltip
                  formatter={(value) => `${fmt.decimal(Number(value))} ثانیه`}
                  labelFormatter={(label) => `نوبت ${label}`}
                  contentStyle={{ borderRadius: 0, borderColor: chart.light, direction: "rtl", fontFamily: "Vazirmatn" }}
                />
                <Legend wrapperStyle={{ direction: "rtl", fontSize: 12 }} />
                <Area type="monotone" dataKey="مشتری" stroke={chart.primary} strokeWidth={2} fill="url(#callerArea)" />
                <Area type="monotone" dataKey="اپراتور" stroke={chart.secondary} strokeWidth={2} fill="url(#agentArea)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          {conversationTurns.length > 30 ? (
            <p className="mt-2 text-center text-[11px] text-slate-400">۳۰ نوبت نخست برای خوانایی نمودار نمایش داده شده است.</p>
          ) : null}
        </section>
      ) : null}

      {hasAudioAnalysis ? <section className="grid items-stretch gap-4 lg:grid-cols-3">
        <div className="relative min-h-0 lg:col-span-2">
          <div className="card title-band flex min-h-0 flex-col lg:absolute lg:inset-0">
          <SectionTitle
            title={isVoicemail ? isQuickDemo ? "متن تست سریع" : "متن پیام صوتی" : "متن مکالمه"}
            description={isVoicemail ? `${fmt.int(conversationTurns.length)} بخش از پیام صوتی` : `${fmt.int(conversationTurns.length)} نوبت گفت‌وگو با تفکیک گوینده`}
            action={
              <div className="flex flex-wrap items-center gap-2">
                {transcriptVersions.length > 1 ? (
                  <select
                    className="input h-9 max-w-40 py-0 text-xs"
                    aria-label="نسخه خام متن"
                    value={selectedRevision?.id ?? call.active_asr_revision_id ?? ""}
                    onChange={(event) => {
                      const next = new URLSearchParams(searchParams);
                      next.set("transcriptVersion", event.target.value);
                      setSearchParams(next, { replace: true });
                    }}
                  >
                    {transcriptVersions.map((revision, index) => (
                      <option key={revision.id} value={revision.id}>
                        نسخه {fmt.int(transcriptVersions.length - index)}{revision.active ? " — فعال" : ""}
                      </option>
                    ))}
                  </select>
                ) : null}
                {selectedRevision && !selectedRevision.active && selectedRevision.status === "succeeded" ? (
                  <button type="button" className="btn h-9 px-3 py-0 text-xs" disabled={processingActionLoading} onClick={() => void activateTranscriptVersion(selectedRevision.id)}>فعال‌سازی نسخه</button>
                ) : null}
                <div className="flex h-9 border border-[color:var(--line)] bg-white p-0.5" role="group" aria-label="نسخه متن">
                  {(["final", "raw"] as const).map((view) => (
                    <button key={view} type="button" aria-pressed={transcriptView === view} className={`whitespace-nowrap px-3 text-xs ${transcriptView === view ? "bg-[#4B6E48] text-white" : "text-slate-600 hover:bg-[#F2F0EF]"}`} onClick={() => { const next = new URLSearchParams(searchParams); next.set("transcript", view); setSearchParams(next, { replace: true }); }}>
                      {view === "final" ? "نسخه نهایی" : "متن خام"}
                    </button>
                  ))}
                </div>
                <OverflowMenu
                  label="عملیات بیشتر متن"
                  actions={[
                    { label: "رونویسی مجدد", onClick: () => void retranscribe(), disabled: !call.audio_available || processingActionLoading || transcriptVersions.some((item) => ["queued", "running"].includes(item.status)) },
                    { label: correctionButtonLabel, onClick: () => void correctTranscript(), disabled: !call.transcript || correctionLoading || correctionActive },
                    { label: "خروجی متن مکالمه", onClick: exportTranscript, disabled: !conversationTurns.length },
                  ]}
                  details={displayRevision ? [
                    { term: "مدل", value: displayRevision.asr_model ?? "نامشخص", ltr: true },
                    { term: "زمان‌بندی", value: displayRevision.timestamp_source ?? "نامشخص", ltr: true },
                    { term: "ایجاد", value: fmt.dateTime(displayRevision.created_at) },
                    { term: "تصحیح", value: displayRevision.correction_status ? ({ queued: "در صف", running: "در حال اجرا", validating: "در حال اعتبارسنجی", succeeded: "موفق", failed: "ناموفق" } as const)[displayRevision.correction_status] : "انجام نشده" },
                  ] : call.asr_model ? [{ term: "مدل", value: call.asr_model, ltr: true }] : undefined}
                />
              </div>
            }
          />
          <div id="correction-action-status" className={`text-xs ${correctionFeedback || correctionActive || (call.correction?.status === "succeeded" && call.correction.uncertain_count > 0) ? "mb-3" : ""}`} role="status" aria-live="polite">
            {correctionFeedback ? (
              <span className={correctionFeedback.tone === "error" ? "text-rose-700" : "text-[#4B6E48]"}>
                {correctionFeedback.message}
              </span>
            ) : correctionActive ? (
              <span className="text-[#4B6E48]">درخواست تصحیح فعال است؛ وضعیت به‌صورت خودکار به‌روز می‌شود.</span>
            ) : call.correction?.status === "succeeded" && call.correction.uncertain_count > 0 ? (
              <span className="text-amber-700">{fmt.int(call.correction.uncertain_count)} بخش نیازمند بررسی است ({fmt.percent(Math.round(call.correction.uncertain_ratio * 100))}).</span>
            ) : null}
          </div>
          {conversationTurns.length === 0 ? (
            <EmptyState
              icon="transcript"
              state={stateKind}
              message={call.processing ? "در حال پیاده‌سازی مکالمه…" : callFailed ? "پیاده‌سازی ناموفق بود. «رونویسی مجدد» را بزنید." : "هنوز پیاده‌سازی نشده است."}
              className="min-h-40 lg:flex-1"
            />
          ) : (
            <div className="max-h-[680px] space-y-5 overflow-y-auto rounded-xl border border-slate-100 bg-slate-50/70 p-3 sm:p-4 lg:min-h-0 lg:max-h-none lg:flex-1">
              {conversationTurns.map((utterance, index) => {
                const caller = speakerLabels[utterance.channel] === "مشتری" || speakerLabels[utterance.channel] === "گوینده ۱" || speakerLabels[utterance.channel] === "همکار تماس‌گیرنده";
                const speaker = speakerLabels[utterance.channel] ?? `کانال ${fmt.int(utterance.channel + 1)}`;
                const turnId = `${utterance.channel}-${utterance.t_start_ms}-${index}`;
                const messageDate = new Date(Date.parse(call.started_at) + utterance.t_start_ms).toISOString();
                return (
                  <ConversationBubble
                    key={turnId}
                    side={caller ? "user" : "assistant"}
                    ariaLabel={speaker}
                    actions={<>
                      <button
                        type="button"
                        className="inline-flex h-7 w-7 items-center justify-center text-[#898989] transition hover:bg-white hover:text-[#4B6E48] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#4B6E48]"
                        onClick={() => void copyTranscriptTurn(turnId, utterance.text)}
                        aria-label={copiedTurnId === turnId ? "پیام کپی شد" : "کپی پیام"}
                        title={copiedTurnId === turnId ? "کپی شد" : "کپی پیام"}
                      >
                        <CopyIcon checked={copiedTurnId === turnId} />
                      </button>
                      <time className="px-1 text-[10px] leading-none text-[#898989]" dateTime={messageDate} title={fmt.dateTime(messageDate)}>
                        {fmt.dateTime(messageDate)}
                      </time>
                    </>}
                    header={
                      <div className={`mb-1.5 flex items-center justify-between gap-6 text-[11px] ${caller ? "text-[#F2F0EF]/75" : "text-[#898989]"}`}>
                        <span className={`font-bold ${caller ? "text-[#F2F0EF]" : "text-[#4B6E48]"}`}>{speaker}{utterance.uncertain ? " — نیازمند بررسی" : ""}</span>
                        <span className="tabular-nums" dir="ltr">{fmt.duration(utterance.t_start_ms)} — {fmt.duration(utterance.t_end_ms)}</span>
                      </div>
                    }
                  >
                    <p className={`whitespace-pre-wrap text-sm leading-7 ${utterance.uncertain ? "underline decoration-amber-400 decoration-2 underline-offset-4" : ""}`} dir="auto">{utterance.text}</p>
                  </ConversationBubble>
                );
              })}
            </div>
          )}
          {call.correction ? (
            <div className={`mt-4 border p-3 text-xs ${call.correction.status === "failed" ? "border-rose-200 bg-rose-50 text-rose-800" : "border-emerald-100 bg-emerald-50/50 text-emerald-800"}`} role="status">
              وضعیت تصحیح: {({ queued: "در صف", running: "در حال اجرا", validating: "در حال اعتبارسنجی", succeeded: "موفق", failed: "ناموفق" } as const)[call.correction.status]}
              {call.correction.provider_model ? ` — مدل: ${call.correction.provider_model}` : ""}
              {call.correction.error_detail ? ` — ${call.correction.error_detail}` : ""}
            </div>
          ) : null}
          </div>
        </div>

        <aside className="space-y-4">


          {insights?.topics?.length ? (
            <div className="card">
              <SectionTitle title="موضوعات مکالمه" />
              <div className="flex flex-wrap gap-2">
                {insights.topics.map((topic) => (
                  <span key={topic} className="rounded-lg border border-violet-100 bg-violet-50 px-3 py-1.5 text-xs text-violet-700">{topic}</span>
                ))}
              </div>
            </div>
          ) : null}

          {call.sales ? (
            <div className="card">
              <SectionTitle title="نتیجه فروش" description="تخمین AI؛ نتیجه رسمی پس از اتصال CRM مشخص می‌شود" />
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-slate-400">مرحله قیف</dt><dd className="mt-1 font-semibold">{call.sales.funnel_stage}</dd></div>
                <div className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-slate-400">نتیجه</dt><dd className="mt-1"><OutcomeBadge outcome={call.sales.outcome} /></dd></div>
                <div className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-slate-400">قطعیت</dt><dd className="mt-1 font-semibold">{call.sales.certainty}</dd></div>
                <div className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-slate-400">اطمینان</dt><dd className="mt-1 font-semibold">{fmt.decimal(call.sales.confidence * 100)}٪</dd></div>
              </dl>
              {call.sales.product ? <p className="mt-3 text-sm"><span className="text-slate-400">محصول: </span>{call.sales.product}</p> : null}
              {call.sales.objections.length ? <div className="mt-3 flex flex-wrap gap-2">{call.sales.objections.map((item) => <span key={item} className="badge bg-amber-50 text-amber-700">{item}</span>)}</div> : null}
              {call.sales.win_loss_reason ? <p className="mt-3 text-sm"><span className="text-slate-400">دلیل: </span>{call.sales.win_loss_reason}</p> : null}
              {call.sales.next_action ? <p className="mt-3 rounded-xl bg-brand-50 p-3 text-sm text-brand-800">اقدام بعدی: {call.sales.next_action}</p> : null}
              {call.sales.evidence.length ? <div className="mt-4 border-t pt-3"><p className="mb-2 text-xs font-bold text-slate-500">شواهد</p>{call.sales.evidence.map((item, index) => <blockquote key={index} className="mb-2 border-r-2 border-brand-300 pr-3 text-xs leading-6 text-slate-600">{item.text}</blockquote>)}</div> : null}
            </div>
          ) : null}

          <div className="card">
            <SectionTitle title="موجودیت‌های استخراج‌شده" />
            {insights?.ner && Object.values(insights.ner).some((values) => values?.length) ? (
              <dl className="space-y-3 text-sm">
                {Object.entries(insights.ner).map(([key, values]) => (
                  <div key={key} className="rounded-xl bg-slate-50 p-3">
                    <dt className="mb-1.5 text-[11px] font-semibold text-slate-400">{NER_LABELS[key] ?? key}</dt>
                    <dd className="text-slate-700" dir="auto">{values?.length ? values.join("، ") : "—"}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <EmptyState icon="entities" compact state={stateKind} message={call.processing ? "در حال استخراج اطلاعات…" : callFailed ? "استخراج اطلاعات کامل نشد." : "موردی استخراج نشده است."} className="min-h-32" />
            )}
          </div>

          {call.prompt_version || call.llm_model || insights?.sentiment_profile?.voice_model ? (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-3 text-[11px] leading-6 text-slate-400">
              {call.prompt_version ? <div>نسخه پرامپت: {call.prompt_version}</div> : null}
              {call.llm_model ? <div>مدل تحلیل: {call.llm_model}</div> : null}
              {insights?.sentiment_profile?.voice_model ? (
                <div className="break-all">
                  مدل تحلیل صدا:{" "}
                  <span dir="ltr">{insights.sentiment_profile.voice_model}</span>
                </div>
              ) : null}
              {call.analysis_run_id ? (
                <div>شناسه اجرا: {fmt.digits(call.analysis_run_id.slice(0, 12))}</div>
              ) : null}
              {call.memory_sha256 ? <div>نسخه مموری: {call.memory_sha256.slice(0, 12)} · {fmt.int(call.memory_versions.length)} مورد</div> : null}
            </div>
          ) : null}
        </aside>
      </section> : null}
      <ConfirmDialog
        open={deleteConfirmationOpen}
        title="حذف تماس"
        description="این تماس، فایل صوتی، متن، تحلیل‌ها و کارهای مرتبط برای همیشه حذف می‌شوند. این عملیات قابل بازگشت نیست."
        confirmLabel="حذف تماس"
        destructive
        busy={deleting}
        onCancel={() => setDeleteConfirmationOpen(false)}
        onConfirm={() => void deleteCall()}
      />
    </div>
  );
}
