import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { chart, palette } from "@cbi/web-shared/theme";
import { Icon } from "@iconify/react";
import alarmClockIcon from "@iconify/icons-fluent-emoji/alarm-clock";
import barChartIcon from "@iconify/icons-fluent-emoji/bar-chart";
import bullseyeIcon from "@iconify/icons-fluent-emoji/bullseye";
import repeatButtonIcon from "@iconify/icons-fluent-emoji/repeat-button";
import starStruckIcon from "@iconify/icons-fluent-emoji/star-struck";
import telephoneReceiverIcon from "@iconify/icons-fluent-emoji/telephone-receiver";
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
import { fmt, INTENT_LABELS, refreshSession, request, tokens } from "../api";
import { CAN_EDIT_TASKS, CAN_HEAR_AUDIO, isOrgAdmin, useAuth } from "../auth";
import FollowUpTaskCard from "../components/FollowUpTaskCard";
import AudioWaveformPlayer from "../components/AudioWaveformPlayer";
import ConversationBubble from "../components/ConversationBubble";
import ConfirmDialog from "../components/ConfirmDialog";
import {
  ErrorBox,
  ProcessingCard,
  SentimentBadge,
  StatusBadge,
  TrajectoryBadge,
} from "../components/Widgets";
import type { CallDetail, DualPartySentiment, FollowUpTask, OperatorScore, ProcessingEvent, Utterance } from "../types";

const NER_LABELS: Record<string, string> = {
  persons: "افراد",
  dates: "تاریخ‌ها",
  amounts: "مبالغ",
  phone_numbers: "شماره‌ها",
  organizations: "سازمان‌ها",
};

const TURN_MERGE_GAP_MS = 1200;
const SPEAKER_COLORS = [chart.primary, chart.secondary];

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

type EmptyStateIcon = "sentiment" | "conversation" | "transcript" | "tasks" | "summary" | "entities";

function EmptyState({
  icon,
  message,
  className = "",
}: {
  icon: EmptyStateIcon;
  message: string;
  className?: string;
}) {
  const paths: Record<EmptyStateIcon, ReactNode> = {
    sentiment: (
      <>
        <path d="M4 18 9 13l4 3 7-9" />
        <path d="M15 7h5v5" />
      </>
    ),
    conversation: (
      <>
        <path d="M5 6.5h9a3 3 0 0 1 3 3v2a3 3 0 0 1-3 3H9l-4 3v-11Z" />
        <path d="M9 10.5h4M19 10v6l-3 2.5" />
      </>
    ),
    transcript: (
      <>
        <path d="M7 3.5h7l4 4V20H7z" />
        <path d="M14 3.5V8h4M10 12h5M10 15.5h5" />
      </>
    ),
    tasks: (
      <>
        <rect x="5" y="4" width="14" height="16" rx="1" />
        <path d="m8.5 10 1.5 1.5 3-3M14.5 10H16M8.5 16h7" />
      </>
    ),
    summary: (
      <>
        <path d="M12 3 13.4 8.6 19 10l-5.6 1.4L12 17l-1.4-5.6L5 10l5.6-1.4z" />
        <path d="m18.5 16 .6 2.4 2.4.6-2.4.6-.6 2.4-.6-2.4-2.4-.6 2.4-.6z" />
      </>
    ),
    entities: (
      <>
        <circle cx="9" cy="8" r="3" />
        <path d="M3.5 19a5.5 5.5 0 0 1 11 0M17 8h4M17 12h4M17 16h3" />
      </>
    ),
  };

  return (
    <div className={`flex flex-col items-center justify-center gap-3 bg-slate-50 px-5 py-8 text-center ${className}`}>
      <span className="flex h-14 w-14 items-center justify-center border border-[#B2AC88] bg-[#F2F0EF] text-[#4B6E48]" aria-hidden="true">
        <svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
          {paths[icon]}
        </svg>
      </span>
      <p className="max-w-md text-sm leading-6 text-slate-400">{message}</p>
    </div>
  );
}

function ActionTooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden w-max max-w-52 -translate-x-1/2 border border-[#B2AC88] bg-[#F2F0EF] px-2.5 py-1.5 text-[11px] font-normal leading-5 text-[#000000] shadow-lg group-hover:block group-focus-within:block"
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}

const CALL_ACTION_CLASS = "flex h-10 w-10 items-center justify-center border border-[#898989] bg-white text-[#000000] transition hover:bg-[#B2AC88] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:opacity-40";

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

      <section className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
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

      <section className="grid items-start gap-4 lg:grid-cols-3">
        <div className="card lg:col-span-2">
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
        <span className="flex h-9 w-9 items-center justify-center border border-[#B2AC88] bg-[#F2F0EF] text-[#000000] transition-transform duration-200 group-open:rotate-180" aria-hidden="true">
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

export default function CallDetailPage() {
  const { callId } = useParams<{ callId: string }>();
  const navigate = useNavigate();
  const { session } = useAuth();
  const [call, setCall] = useState<CallDetail | null>(null);
  const [operatorScore, setOperatorScore] = useState<OperatorScore | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [sentimentSource, setSentimentSource] = useState<"text" | "voice">("voice");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioLoading, setAudioLoading] = useState(false);
  const [correctionLoading, setCorrectionLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirmationOpen, setDeleteConfirmationOpen] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  }, [audioUrl]);

  useEffect(() => {
    setAudioUrl(null);
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
        void request<OperatorScore | null>(`/v1/calls/${callId}/operator-score`).then(setOperatorScore).catch(() => setOperatorScore(null));
        setError(null);
        processing = data.processing;
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
    setError(null);
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
      const blob = await response.blob();
      if (!blob.size) throw new Error("فایل صوتی خالی است");
      const url = URL.createObjectURL(blob);
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
      setAudioLoading(false);
    }
  }

  async function reanalyze() {
    if (!call?.transcript) {
      setError("متن تماس هنوز آماده نشده است؛ پس از اتمام تبدیل صوت به متن دوباره تلاش کنید.");
      return;
    }
    setError(null);
    try {
      await request<void>(`/v1/calls/${callId}/reanalyze`, { method: "POST" });
      setNotice("درخواست تحلیل مجدد ثبت شد (بدون هزینه اضافه).");
      setReload((value) => value + 1);
    } catch (err) {
      setError((err as Error).message);
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
    try {
      await request<void>(`/v1/calls/${callId}/correct-transcript`, { method: "POST" });
      setNotice("نسخهٔ اصلاح‌شدهٔ متن آماده شد؛ تحلیل تماس همچنان بر پایهٔ متن خام انجام می‌شود.");
      setReload((value) => value + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCorrectionLoading(false);
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
  const conversationTurns = buildConversationTurns(call.utterances);
  const callerDuration = conversationTurns
    .filter((turn) => turn.channel === 0)
    .reduce((total, turn) => total + Math.max(0, turn.t_end_ms - turn.t_start_ms), 0);
  const agentDuration = conversationTurns
    .filter((turn) => turn.channel !== 0)
    .reduce((total, turn) => total + Math.max(0, turn.t_end_ms - turn.t_start_ms), 0);
  const totalSpeechDuration = callerDuration + agentDuration;
  const speechCoverage = call.duration_ms
    ? Math.min(100, Math.round((totalSpeechDuration / call.duration_ms) * 100))
    : 0;
  const averageTurnDuration = conversationTurns.length
    ? Math.round(totalSpeechDuration / conversationTurns.length)
    : 0;
  const speakerData = [
    { name: "مشتری", value: callerDuration },
    { name: "اپراتور", value: agentDuration },
  ].filter((item) => item.value > 0);
  const activeSentimentProfile =
    sentimentSource === "voice"
      ? (insights?.sentiment_profile?.voice ?? insights?.sentiment_profile?.text)
      : (insights?.sentiment_profile?.text ?? insights?.sentiment_profile?.voice);
  const sentimentData = sentimentChartData(activeSentimentProfile);
  const sentimentScore = insights?.sentiment_score;

  return (
    <div className="space-y-5">
      <ErrorBox message={error} />

      {call.recovery_pending ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="status">
          ارسال تحلیل با تأخیر روبه‌رو شده است؛ بازیابی خودکار فعال است و نیازی به ثبت تحلیل مجدد نیست.
        </div>
      ) : null}

      <section className="call-detail-hero relative overflow-visible border border-[#B2AC88] bg-[#F2F0EF] shadow-sm">
        <div className="absolute inset-x-0 top-0 h-1 bg-[#4B6E48]" />
        <div className="relative p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs text-[#000000]">
              <Link className="transition hover:text-[#000000]" to="/calls">تماس‌ها</Link>
              <span>/</span>
              <span className="font-medium text-[#000000]">جزئیات و تحلیل تماس</span>
            </div>
            <div className="call-header-status flex flex-wrap items-center gap-2">
              <StatusBadge status={call.status} />
              <span className="bg-[#B2AC88] px-2.5 py-1 text-[11px] text-[#000000]">
                شناسه {fmt.digits(call.id.slice(0, 8))}
              </span>
            </div>
          </div>

          <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
            <div>
              <div className="mb-2 flex items-center gap-3">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center bg-[#F2F0EF] text-[#000000]" aria-hidden="true">
                  <Icon icon={telephoneReceiverIcon} className="h-9 w-9" />
                </span>
                <div>
                  <p className="text-xs text-[#000000]">مکالمه تلفنی</p>
                  <h1 className="mt-0.5 text-xl font-extrabold text-[#000000] sm:text-2xl" dir="rtl">
                    {call.dialed_number ? fmt.digits(call.dialed_number) : "—"}{" "}
                    <span className="px-1 text-[#B2AC88]">←</span>{" "}
                    {call.caller_number ? fmt.digits(call.caller_number) : "—"}
                  </h1>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-[#000000]">
                <span>تاریخ تماس: {fmt.dateTime(call.started_at)}</span>
                <span>مدت: {fmt.duration(call.duration_ms)}</span>
                {call.direction ? <span>جهت: {call.direction}</span> : null}
                {call.agent_extension ? <span>داخلی: {fmt.digits(call.agent_extension)}</span> : null}
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
                <ActionTooltip label={audioLoading ? "در حال دریافت صوت…" : "پخش فایل صوتی"}>
                  <button
                    type="button"
                    className={CALL_ACTION_CLASS}
                    onClick={() => void playAudio()}
                    disabled={audioLoading}
                    aria-label={audioLoading ? "در حال دریافت صوت" : "پخش فایل صوتی"}
                  >
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                      <path d="M5 9v6h4l5 4V5L9 9H5Z" />
                      <path d="M18 9a4 4 0 0 1 0 6M20.5 6.5a8 8 0 0 1 0 11" />
                    </svg>
                  </button>
                </ActionTooltip>
              ) : null}
              {session?.role === "org_admin" || session?.role === "operator" ? (
                <ActionTooltip label="پرسش درباره این تماس">
                  <Link className={CALL_ACTION_CLASS} to={`/assistant?call_id=${call.id}`} aria-label="پرسش درباره این تماس">
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                      <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v8Z" />
                      <path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .8-1 1.7M12 16h.01" />
                    </svg>
                  </Link>
                </ActionTooltip>
              ) : null}
              <ActionTooltip label={call.transcript ? "تحلیل مجدد" : "پس از آماده‌شدن متن تماس، تحلیل مجدد فعال می‌شود"}>
                <button type="button" className={CALL_ACTION_CLASS} onClick={() => void reanalyze()} disabled={!call.transcript} aria-label="تحلیل مجدد">
                  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                    <path d="M20 7v5h-5M4 17v-5h5" />
                    <path d="M6.1 9A7 7 0 0 1 18.7 6.7L20 12M4 12l1.3 5.3A7 7 0 0 0 17.9 15" />
                  </svg>
                </button>
              </ActionTooltip>
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
            <div className="mt-5 border-t border-[#B2AC88] pt-4">
              <AudioWaveformPlayer
                audioRef={audioRef}
                downloadName={`call-${call.id}-audio`}
                src={audioUrl}
                onError={() => setError("مرورگر قادر به پخش این فایل صوتی نیست.")}
              />
            </div>
          ) : null}
        </div>
      </section>

      {notice ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{notice}</div>
      ) : null}

      <ProcessingCard status={call.status} progressPct={call.progress_pct} detail={call.progress_detail} />

      {call.status.startsWith("failed") && (call.error_code || call.error_detail) ? (
        <section className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-4 text-rose-800">
          <h2 className="text-sm font-bold">علت توقف پردازش</h2>
          {call.error_code ? <p className="mt-1 text-xs font-semibold">کد خطا: {call.error_code}</p> : null}
          {call.error_detail ? <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-6" dir="auto">{call.error_detail}</p> : null}
        </section>
      ) : null}

      <ProcessingTimeline events={call.processing_events ?? []} />

      <section className="card overflow-visible">
        <SectionTitle
          title="کارهای قابل پیگیری"
          description="موارد عملیاتی استخراج‌شده از تماس؛ می‌توانید آن‌ها را ویرایش یا انجام‌شده کنید"
          action={
            <Link className="text-xs text-brand-700 hover:underline" to="/tasks">
              همه کارها
            </Link>
          }
        />
        {tasks.length === 0 ? (
          <EmptyState icon="tasks" message="موردی ثبت نشده است." className="min-h-36" />
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
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="مدت کل تماس" value={fmt.duration(call.duration_ms)} hint="از شروع تا پایان مکالمه" icon={<Icon icon={alarmClockIcon} className="h-14 w-14" />} />
        <MetricCard
          label="نوبت‌های گفت‌وگو"
          value={fmt.int(conversationTurns.length)}
          hint={`میانگین هر نوبت ${fmt.duration(averageTurnDuration)}`}
          icon={<Icon icon={repeatButtonIcon} className="h-14 w-14" />}
        />
        <MetricCard
          label="پوشش گفتار"
          value={fmt.percent(speechCoverage)}
          hint="نسبت گفتار تشخیص‌داده‌شده به تماس"
          icon={<Icon icon={barChartIcon} className="h-14 w-14" />}
        />
        <MetricCard
          label="امتیاز احساس"
          value={sentimentScore == null ? "—" : fmt.percent(sentimentScore * 100)}
          hint={insights?.intent ? (INTENT_LABELS[insights.intent] ?? insights.intent) : "قصد تماس نامشخص"}
          icon={<Icon icon={bullseyeIcon} className="h-14 w-14" />}
        />
        <MetricCard label="امتیاز عملکرد" value={operatorScore?.total_score == null ? "—" : fmt.decimal(operatorScore.total_score)} hint={operatorScore?.status === "succeeded" ? operatorScore.operator_label : "در حال ارزیابی"} icon={<Icon icon={starStruckIcon} className="h-14 w-14" />} />
      </section>

      {operatorScore?.criteria_scores?.length ? <section className="card"><SectionTitle title="ارزیابی عملکرد اپراتور" description={operatorScore.operator_label} /><div className="grid gap-3 md:grid-cols-2">{operatorScore.criteria_scores.map((criterion) => <div key={criterion.title} className="rounded-xl border border-slate-200 p-3"><div className="flex justify-between"><strong>{criterion.title}</strong><span>{fmt.decimal(criterion.score)}</span></div>{criterion.evidence ? <p className="mt-2 text-sm text-slate-600">{criterion.evidence}</p> : null}</div>)}</div></section> : null}

      <section className="grid gap-4 xl:grid-cols-5">
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
            <EmptyState icon="sentiment" message="هنوز داده کافی برای ترسیم روند احساس وجود ندارد." className="h-64" />
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
            <EmptyState icon="conversation" message="داده گفتاری برای این تماس ثبت نشده است." className="h-64" />
          )}
        </div>
      </section>

      {conversationTurns.length ? (
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

      <section className="grid items-start gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <div className="card">
          <SectionTitle
            title="متن مکالمه"
            description={`${fmt.int(conversationTurns.length)} نوبت گفت‌وگو با تفکیک گوینده`}
            action={
              <div className="flex items-center gap-2">
                <button
                  className="btn-ghost inline-flex h-9 items-center justify-center bg-white px-3 py-0 text-xs"
                  onClick={() => void correctTranscript()}
                  disabled={!call.transcript || correctionLoading}
                >
                  {correctionLoading ? "در حال تصحیح…" : call.corrected_transcript ? "تصحیح دوباره متن" : "تصحیح متن"}
                </button>
                {call.asr_model ? (
                  <button
                    type="button"
                    className="group relative flex h-9 w-9 shrink-0 items-center justify-center border border-[#898989] bg-white text-[#4B6E48] hover:bg-[#F2F0EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]"
                    aria-label={`مدل تبدیل گفتار: ${call.asr_model}`}
                  >
                    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true">
                      <circle cx="12" cy="12" r="9" />
                      <path d="M12 11v6M12 7.5v.5" />
                    </svg>
                    <span className="pointer-events-none absolute left-0 top-full z-20 mt-2 hidden w-max max-w-[min(28rem,calc(100vw-3rem))] break-all border border-[#B2AC88] bg-[#F2F0EF] px-3 py-2 text-left text-[11px] font-normal leading-5 text-[#000000] shadow-lg group-hover:block group-focus:block" dir="ltr" role="tooltip">
                      {call.asr_model}
                    </span>
                  </button>
                ) : null}
              </div>
            }
          />
          {conversationTurns.length === 0 ? (
            <EmptyState
              icon="transcript"
              message={call.processing ? "در حال پیاده‌سازی مکالمه…" : "هنوز پیاده‌سازی نشده است."}
              className="min-h-40"
            />
          ) : (
            <div className="max-h-[680px] space-y-5 overflow-y-auto rounded-xl border border-slate-100 bg-slate-50/70 p-3 sm:p-4">
              {conversationTurns.map((utterance, index) => {
                const caller = utterance.channel === 0;
                return (
                  <ConversationBubble
                    key={`${utterance.channel}-${utterance.t_start_ms}-${index}`}
                    side={caller ? "user" : "assistant"}
                    ariaLabel={caller ? "مشتری" : "اپراتور"}
                    header={
                      <div className={`mb-1.5 flex items-center justify-between gap-6 text-[11px] ${caller ? "text-[#F2F0EF]/75" : "text-[#898989]"}`}>
                        <span className={`font-bold ${caller ? "text-[#F2F0EF]" : "text-[#4B6E48]"}`}>{caller ? "مشتری" : "اپراتور"}</span>
                        <span className="tabular-nums" dir="ltr">{fmt.duration(utterance.t_start_ms)} — {fmt.duration(utterance.t_end_ms)}</span>
                      </div>
                    }
                  >
                    <p className="whitespace-pre-wrap text-sm leading-7" dir="auto">{utterance.text}</p>
                  </ConversationBubble>
                );
              })}
            </div>
          )}
          {call.corrected_transcript ? (
            <div className="mt-4 rounded-xl border border-emerald-100 bg-emerald-50/50 p-4">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-bold text-emerald-800">نسخهٔ اصلاح‌شده</h3>
                {call.corrected_transcript_at ? <span className="text-[11px] text-emerald-700">{fmt.dateTime(call.corrected_transcript_at)}</span> : null}
              </div>
              <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700" dir="auto">{call.corrected_transcript}</p>
            </div>
          ) : null}
          </div>

        </div>

        <aside className="space-y-4">
          <div className="card">
            <SectionTitle title="خلاصه هوشمند" description="چکیده محتوای تماس" />
            {insights?.summary ? (
              <p className="text-sm leading-7 text-slate-700">{insights.summary}</p>
            ) : (
              <EmptyState
                icon="summary"
                message={call.processing ? "خلاصه در حال آماده‌سازی است…" : "خلاصه‌ای برای این تماس ثبت نشده است."}
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
                <div className="rounded-xl bg-slate-50 p-3"><dt className="text-xs text-slate-400">نتیجه</dt><dd className="mt-1 font-semibold">{call.sales.outcome}</dd></div>
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
              <EmptyState icon="entities" message="موردی استخراج نشده است." className="min-h-32" />
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
            </div>
          ) : null}
        </aside>
      </section>
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
