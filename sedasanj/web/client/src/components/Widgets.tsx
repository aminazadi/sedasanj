import type { ReactNode } from "react";
import { fmt, SENTIMENT_LABELS, STATUS_LABELS, TRAJECTORY_LABELS } from "../api";
import type { PartySentiment, SentimentPoint } from "../types";

const PIPELINE_STEPS: { label: string; hint: string; statuses: string[] }[] = [
  { label: "دریافت و ذخیره", hint: "آماده‌سازی فایل صوتی", statuses: ["received", "reserved", "stored"] },
  { label: "تبدیل گفتار", hint: "پیاده‌سازی مکالمه", statuses: ["transcribing", "transcribed"] },
  { label: "تحلیل هوشمند", hint: "تحلیل لحن، احساس و بینش", statuses: ["emotion_queued", "emotion_analyzing", "analyzing", "analyzed"] },
  { label: "تکمیل گزارش", hint: "ثبت و آماده نمایش", statuses: ["billed", "notified", "complete"] },
];

export function Stat({ title, value, hint, tone }: { title: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="panel-stat-card card">
      <div className="text-sm text-slate-500">{title}</div>
      <div className={`mt-1 text-2xl font-bold ${tone ?? ""}`}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-400">{hint}</div> : null}
    </div>
  );
}

export function Pagination({
  page,
  hasPrevious,
  hasNext,
  total,
  loading = false,
  onPrevious,
  onNext,
}: {
  page: number;
  hasPrevious: boolean;
  hasNext: boolean;
  total?: number;
  loading?: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (!hasPrevious && !hasNext) return null;
  return (
    <nav className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4" aria-label="صفحه‌بندی">
      <span className="text-xs text-slate-500">صفحه {fmt.int(page)}{typeof total === "number" ? ` · ${fmt.int(total)} مورد` : ""}</span>
      <div className="flex gap-2">
        <button className="btn-ghost text-sm" type="button" disabled={loading || !hasPrevious} onClick={onPrevious}>صفحه قبل</button>
        <button className="btn-ghost text-sm" type="button" disabled={loading || !hasNext} onClick={onNext}>صفحه بعد</button>
      </div>
    </nav>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "complete"
      ? "bg-emerald-50 text-emerald-700"
      : status.startsWith("failed")
        ? "bg-rose-50 text-rose-700"
        : "bg-amber-50 text-amber-700";
  return <span className={`badge ${tone}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export function ProcessingCard({
  status,
  progressPct,
  detail,
}: {
  status: string;
  progressPct: number;
  detail: string | null;
}) {
  const failed = status.startsWith("failed");
  const current = PIPELINE_STEPS.findIndex((step) => step.statuses.includes(status));
  const complete = status === "complete";
  const safeProgress = complete ? 100 : Math.max(0, Math.min(progressPct, 100));
  const activeIndex =
    current >= 0 ? current : failed ? Math.min(3, Math.max(0, Math.floor(safeProgress / 25))) : 0;
  return (
    <section className="processing-card-dots card overflow-hidden !p-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div>
          <div className="mb-1 flex items-center gap-2">
            <span
              className={`h-2.5 w-2.5 rounded-full ${
                failed
                  ? "bg-rose-500"
                  : complete
                    ? "bg-emerald-500"
                    : "animate-pulse bg-[#4B6E48]"
              }`}
            />
            <h2 className="font-bold text-slate-800">مسیر تحلیل تماس</h2>
          </div>
          <p className="text-xs text-slate-500">
            {detail || STATUS_LABELS[status] || status}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`rounded-full px-3 py-1 text-xs font-semibold ${
              failed
                ? "bg-rose-50 text-rose-700"
                : complete
                  ? "bg-emerald-50 text-emerald-700"
                  : "bg-[#F2F0EF] text-[#4B6E48]"
            }`}
          >
            {failed ? "نیازمند بررسی" : complete ? "تحلیل کامل شد" : "در حال پردازش"}
          </span>
          <span className="min-w-10 text-left text-sm font-bold tabular-nums text-slate-700">
            {fmt.percent(safeProgress)}
          </span>
        </div>
      </div>
      <div className="h-1 bg-slate-100" aria-hidden="true">
        <div
          className={`h-full transition-[width] duration-700 ${
            failed ? "bg-rose-500" : complete ? "bg-emerald-500" : "bg-[#4B6E48]"
          }`}
          style={{ width: `${safeProgress}%` }}
        />
      </div>
      <ol className="grid gap-0 px-4 py-5 sm:grid-cols-4 sm:px-6">
        {PIPELINE_STEPS.map((step, index) => {
          const done = complete || (!failed && activeIndex > index);
          const active = !complete && activeIndex === index;
          return (
            <li
              key={step.label}
              className="relative flex min-h-16 items-start gap-3 pb-4 last:pb-0 sm:block sm:min-h-0 sm:px-2 sm:pb-0 sm:text-center"
            >
              {index < PIPELINE_STEPS.length - 1 ? (
                <span
                  className={`absolute right-[15px] top-8 h-[calc(100%-1.5rem)] w-px sm:right-1/2 sm:top-4 sm:h-px sm:w-full ${
                    done ? "bg-emerald-300" : "bg-slate-200"
                  }`}
                  aria-hidden="true"
                />
              ) : null}
              <span
                className={`relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 font-bold transition-colors sm:mx-auto sm:mb-3 ${done ? "text-xl leading-none" : "text-xs"} ${
                  done
                    ? "border-emerald-500 bg-emerald-500 text-white"
                    : active
                      ? failed
                        ? "border-rose-500 bg-rose-50 text-rose-600"
                        : "border-[#4B6E48] bg-[#4B6E48] text-white shadow-[0_0_0_5px_rgb(75_110_72_/_0.10)]"
                      : "border-slate-200 bg-white text-slate-400"
                }`}
              >
                {done ? "✓" : fmt.int(index + 1)}
              </span>
              <span className="block pt-0.5 sm:pt-0">
                <span
                  className={`block text-sm font-semibold ${
                    done
                      ? "text-emerald-700"
                      : active
                        ? failed
                          ? "text-rose-700"
                          : "text-[#4B6E48]"
                        : "text-slate-400"
                  }`}
                >
                  {step.label}
                </span>
                <span className="mt-1 block text-[11px] leading-5 text-slate-400">{step.hint}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function SentimentBadge({ sentiment }: { sentiment: string | null }) {
  if (!sentiment) return <span className="text-slate-400">—</span>;
  const tones: Record<string, string> = {
    angry: "bg-red-50 text-red-700",
    sad: "bg-orange-50 text-orange-700",
    neutral: "bg-slate-100 text-slate-600",
    satisfied: "bg-sky-50 text-sky-700",
    happy: "bg-emerald-50 text-emerald-700",
  };
  const tone = tones[sentiment] ?? "bg-slate-100 text-slate-600";
  return <span className={`badge ${tone}`}>{SENTIMENT_LABELS[sentiment] ?? sentiment}</span>;
}

export function TrajectoryBadge({ trajectory }: { trajectory: string | null | undefined }) {
  if (!trajectory) return null;
  const tone =
    trajectory === "improved"
      ? "bg-emerald-50 text-emerald-700"
      : trajectory === "worsened"
        ? "bg-rose-50 text-rose-700"
        : "bg-slate-100 text-slate-600";
  const mark = trajectory === "improved" ? "↑" : trajectory === "worsened" ? "↓" : "→";
  return (
    <span className={`badge ${tone}`}>
      {mark} {TRAJECTORY_LABELS[trajectory] ?? trajectory}
    </span>
  );
}

function PointLabel({ point }: { point: SentimentPoint }) {
  return (
    <span className="inline-flex flex-col items-center gap-1">
      <SentimentBadge sentiment={point.label} />
      <span className="text-[11px] tabular-nums text-slate-400">{fmt.percent(point.score * 100)}</span>
    </span>
  );
}

export function PartySentimentCard({
  title,
  party,
}: {
  title: string;
  party: PartySentiment | null | undefined;
}) {
  if (!party) {
    return (
      <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
        <h3 className="mb-2 font-semibold">{title}</h3>
        <p className="text-sm text-slate-400">گفتاری برای این کانال ثبت نشده است.</p>
      </div>
    );
  }
  const deltaLabel = `${party.delta > 0 ? "+" : ""}${party.delta.toLocaleString("fa-IR", {
    maximumFractionDigits: 2,
  })}`;
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="font-semibold">{title}</h3>
        <TrajectoryBadge trajectory={party.trajectory} />
      </div>
      <dl className="grid grid-cols-3 gap-2 text-center text-sm">
        <div>
          <dt className="mb-2 text-xs text-slate-500">شروع</dt>
          <dd>
            <PointLabel point={party.start} />
          </dd>
        </div>
        <div>
          <dt className="mb-2 text-xs text-slate-500">کل مکالمه</dt>
          <dd>
            <PointLabel point={party.overall} />
          </dd>
        </div>
        <div>
          <dt className="mb-2 text-xs text-slate-500">پایان</dt>
          <dd>
            <PointLabel point={party.end} />
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-center text-xs text-slate-500">تغییر احساس: {deltaLabel}</p>
    </div>
  );
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-2 text-sm text-rose-700">
      {message}
    </div>
  );
}

export function Loading({ children = "در حال بارگذاری…" }: { children?: ReactNode }) {
  return <div className="py-10 text-center text-slate-400">{children}</div>;
}

export function Empty({ children = "موردی یافت نشد." }: { children?: ReactNode }) {
  return <div className="py-10 text-center text-slate-400">{children}</div>;
}

export function SummaryCell({ summary }: { summary: string | null }) {
  const text = summary ?? "—";
  return (
    <td className="max-w-sm truncate" title={summary ?? undefined}>
      {text}
    </td>
  );
}
