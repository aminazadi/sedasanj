import { useEffect, useState, type ReactNode } from "react";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { Skeleton, SkeletonRegion } from "@cbi/web-shared/components/Skeleton";
import { fmt, request } from "../api";
import { isOrgAdmin, useAuth } from "../auth";
import MarkdownMessage from "./MarkdownMessage";
import { CallStateArt, type CallStateKind } from "./CallStateArt";
import { ErrorBox } from "./Widgets";
import type { CoachDimension, CoachIssue, CoachPattern, CoachSeverity, OperatorCoach } from "../types";

const POLL_MS = 3000;

const SEVERITY_LABELS: Record<CoachSeverity, string> = { high: "اثر زیاد", medium: "اثر متوسط", low: "اثر کم" };
const SEVERITY_BAR: Record<CoachSeverity, string> = { high: "bg-rose-600", medium: "bg-amber-500", low: "bg-slate-400" };
const SEVERITY_TONE: Record<CoachSeverity, string> = {
  high: "bg-rose-50 text-rose-700",
  medium: "bg-amber-50 text-amber-700",
  low: "bg-slate-100 text-slate-600",
};
const PATTERN_LABELS: Record<CoachPattern, string> = { new: "جدید", recurring: "تکراری", improving: "در حال بهبود" };
const PATTERN_TONE: Record<CoachPattern, string> = {
  new: "bg-slate-100 text-slate-600",
  recurring: "bg-rose-50 text-rose-700",
  improving: "bg-emerald-50 text-emerald-700",
};
const DIMENSION_LABELS: Record<string, string> = {
  opening: "شروع و معرفی",
  listening: "گوش‌دادن فعال",
  empathy: "همدلی",
  discovery: "کشف نیاز",
  clarity: "شفافیت پاسخ",
  ownership: "مسئولیت‌پذیری",
  objection: "مدیریت اعتراض",
  closing: "جمع‌بندی و گام بعدی",
  tone: "لحن",
};
const SKIP_MESSAGES: Record<string, string> = {
  disabled: "مربی ارتباط با مشتری در تنظیمات غیرفعال است.",
  not_answered: "این تماس پاسخ داده نشده است، پس تحلیل مربی ندارد.",
  no_transcript: "متن این تماس هنوز آماده نیست.",
  too_short: "تماس برای تحلیل مربی بسیار کوتاه بود.",
  no_operator_speech: "در این تماس صدای اپراتور تشخیص داده نشد.",
  call_missing: "اطلاعات تحلیل این تماس کامل نیست.",
};

function scoreTone(score: number): string {
  if (score >= 75) return "bg-[#4B6E48]";
  if (score >= 50) return "bg-amber-500";
  return "bg-rose-600";
}

function CoachState({ kind, message, children }: { kind: CallStateKind; message: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 bg-slate-50 px-5 py-6 text-center">
      <CallStateArt section="coach" kind={kind} compact />
      <p
        className={`max-w-md text-sm leading-6 ${kind === "failed" ? "text-[#B5543F]" : "text-slate-500"}`}
        role={kind === "empty" ? undefined : "status"}
      >
        {message}
      </p>
      {children}
    </div>
  );
}

function Chip({ className, children }: { className: string; children: string }) {
  return <span className={`inline-flex h-6 items-center px-2 text-xs font-medium ${className}`}>{children}</span>;
}

function DimensionBar({ item }: { item: CoachDimension }) {
  const label = DIMENSION_LABELS[item.key] ?? item.label_fa ?? item.key;
  return (
    <li className="border border-[color:var(--line)] bg-white p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-slate-800">{label}</span>
        <span className="text-sm font-bold text-slate-700" dir="ltr">
          {item.score === null ? "—" : fmt.int(item.score)}
        </span>
      </div>
      <div className="mt-2 h-2 bg-[#F2F0EF]" role="img" aria-label={`${label}: ${item.score ?? "نامشخص"}`}>
        {item.score === null ? null : <div className={`h-2 ${scoreTone(item.score)}`} style={{ width: `${item.score}%` }} />}
      </div>
      {item.verdict ? <p className="mt-2 text-xs leading-6 text-slate-500">{item.verdict}</p> : null}
    </li>
  );
}

function IssueCard({ issue, index }: { issue: CoachIssue; index: number }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(issue.better_phrase);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }
  return (
    <li className="flex border border-[color:var(--line)] bg-white">
      <span className={`w-1 shrink-0 ${SEVERITY_BAR[issue.severity]}`} aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-bold text-slate-800">
            {fmt.int(index + 1)}. {issue.title}
          </h3>
          <Chip className={SEVERITY_TONE[issue.severity]}>{SEVERITY_LABELS[issue.severity]}</Chip>
          <Chip className={PATTERN_TONE[issue.pattern]}>{PATTERN_LABELS[issue.pattern]}</Chip>
          {issue.dimension && DIMENSION_LABELS[issue.dimension] ? (
            <Chip className="bg-[#F2F0EF] text-slate-600">{DIMENSION_LABELS[issue.dimension]}</Chip>
          ) : null}
        </div>
        {issue.pattern_note ? <p className="text-xs leading-6 text-slate-500">{issue.pattern_note}</p> : null}
        <blockquote className="border-r-4 border-[#B2AC88] bg-[#F2F0EF] px-3 py-2 text-sm leading-7 text-slate-700">
          «{issue.evidence_quote}»
          {issue.turn_ref ? <span className="mr-2 text-xs text-slate-400">{issue.turn_ref}</span> : null}
        </blockquote>
        {issue.why_it_hurts ? <p className="text-sm leading-7 text-slate-600">{issue.why_it_hurts}</p> : null}
        {issue.better_phrase ? (
          <div className="border border-[#4B6E48]/40 bg-[#4B6E48]/5 p-3">
            <div className="flex items-start justify-between gap-3">
              <p className="text-sm font-medium leading-7 text-[#37533a]">{issue.better_phrase}</p>
              <button type="button" className="btn-ghost h-8 shrink-0 px-2 py-0 text-xs" onClick={copy}>
                {copied ? "کپی شد" : "کپی جمله"}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </li>
  );
}

function BulletList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="border border-[color:var(--line)] bg-white p-4">
      <h3 className="mb-2 font-bold text-slate-800">{title}</h3>
      <ul className="space-y-2 text-sm leading-7 text-slate-600">
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 bg-[#4B6E48]" aria-hidden="true" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CoachBody({ coach }: { coach: OperatorCoach }) {
  const result = coach.result;
  if (!result) return null;
  if (result.insufficient_evidence) {
    return (
      <CoachState
        kind="empty"
        message={`شواهد این تماس برای تحلیل دقیق مربی کافی نبود.${result.insufficient_reason ? ` ${result.insufficient_reason}` : ""}`}
      />
    );
  }
  const scored = result.dimensions.filter((item) => item.score !== null || item.verdict);
  return (
    <div className="space-y-5">
      <div className="coach-pattern border border-[color:var(--line)] p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <p className="text-lg font-bold leading-8 text-slate-900">{result.headline}</p>
          {result.confidence === "low" ? <Chip className="bg-amber-50 text-amber-700">اطمینان پایین</Chip> : null}
        </div>
        <div className="mt-3 text-sm leading-8 text-slate-700">
          <MarkdownMessage content={result.narrative} />
        </div>
      </div>
      {scored.length > 0 ? (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {scored.map((item) => (
            <DimensionBar key={item.key} item={item} />
          ))}
        </ul>
      ) : null}
      {result.issues.length > 0 ? (
        <ul className="space-y-3">
          {result.issues.map((issue, index) => (
            <IssueCard key={`${issue.title}-${index}`} issue={issue} index={index} />
          ))}
        </ul>
      ) : (
        <p className="bg-[#F2F0EF] px-4 py-4 text-sm text-slate-600">مشکل قابل‌اتکایی با شاهد در این تماس پیدا نشد.</p>
      )}
      <div className="grid gap-3 lg:grid-cols-2">
        <BulletList title="نقاط قوت" items={result.strengths.map((item) => (item.evidence_quote ? `${item.title} — «${item.evidence_quote}»` : item.title))} />
        <BulletList title="فرصت‌های از دست‌رفته" items={result.missed_opportunities} />
        <BulletList title="تمرین برای تماس بعدی" items={result.next_call_drills} />
      </div>
    </div>
  );
}

export default function OperatorCoachSection({ callId, canRegenerate }: { callId: string; canRegenerate: boolean }) {
  const { session } = useAuth();
  const resource = useResource<OperatorCoach | null>(
    (signal) => request<OperatorCoach | null>(`/v1/calls/${callId}/operator-coach`, { signal }),
    [callId],
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  const coach = resource.data ?? null;
  const pending = coach?.status === "queued" || coach?.status === "running";
  const { reload } = resource;

  useEffect(() => {
    if (!pending) return undefined;
    const timer = window.setInterval(() => reload({ silent: true }), POLL_MS);
    return () => window.clearInterval(timer);
  }, [pending, reload]);

  async function regenerate() {
    setRequesting(true);
    setActionError(null);
    try {
      await request(`/v1/calls/${callId}/operator-coach/regenerate`, { method: "POST" });
      reload({ silent: true });
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "درخواست انجام نشد؛ دوباره تلاش کنید.");
    } finally {
      setRequesting(false);
    }
  }

  const showOperator = isOrgAdmin(session?.role) && coach?.operator_label && coach.operator_label !== "—";
  const description = showOperator
    ? `پیشنهادهای دقیق برای بهتر شدن ارتباط با مشتری — ${coach?.operator_label}`
    : "پیشنهادهای دقیق و مبتنی بر مکالمه برای بهتر شدن ارتباط اپراتور با مشتری";

  return (
    <section className="card overflow-visible" aria-live="polite">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-bold text-slate-800">مربی ارتباط با مشتری</h2>
          <p className="mt-1 text-xs text-slate-400">{description}</p>
        </div>
        {canRegenerate && coach && !pending ? (
          <button type="button" className="btn-ghost inline-flex h-9 items-center px-3 py-0 text-xs" disabled={requesting} onClick={regenerate}>
            {requesting ? "در حال ارسال…" : "تحلیل دوباره"}
          </button>
        ) : null}
      </div>
      <ErrorBox message={actionError ?? resource.error} />
      {resource.status === "initial" ? (
        <SkeletonRegion label="در حال بارگذاری مربی">
          <div className="space-y-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        </SkeletonRegion>
      ) : coach === null ? (
        <CoachState kind="empty" message="هنوز تحلیل مربی برای این تماس انجام نشده است. پس از پایان تحلیل تماس، خودکار انجام می‌شود.">
          {canRegenerate ? (
            <button type="button" className="btn h-9 px-3 py-0 text-xs" disabled={requesting} onClick={regenerate}>
              {requesting ? "در حال ارسال…" : "درخواست تحلیل مربی"}
            </button>
          ) : null}
        </CoachState>
      ) : pending ? (
        <CoachState kind="processing" message="مربی در حال بررسی مکالمه و سابقهٔ اپراتور است؛ معمولاً چند دقیقه طول می‌کشد." />
      ) : coach.status === "skipped" ? (
        <CoachState kind="empty" message={SKIP_MESSAGES[coach.skip_reason ?? ""] ?? "برای این تماس تحلیل مربی انجام نشد."} />
      ) : coach.status === "failed" ? (
        <CoachState kind="failed" message={`تحلیل مربی ناموفق بود. ${coach.error_detail ?? ""} با «تحلیل دوباره» دوباره تلاش کنید؛ اگر تکرار شد، مدیر سیستم تنظیمات مدل مربی را بررسی کند.`}>
          {coach.error_code ? <p className="text-xs text-slate-400" dir="ltr">{coach.error_code}</p> : null}
        </CoachState>
      ) : (
        <CoachBody coach={coach} />
      )}
    </section>
  );
}
