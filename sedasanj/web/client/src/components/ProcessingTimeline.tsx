import { fmt } from "../api";
import type { ProcessingEvent } from "../types";

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

export default function ProcessingTimeline({ events }: { events: ProcessingEvent[] }) {
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
                      <span className="font-semibold text-slate-700">{EVENT_KIND_LABELS[event.kind] ?? event.kind}</span>
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
