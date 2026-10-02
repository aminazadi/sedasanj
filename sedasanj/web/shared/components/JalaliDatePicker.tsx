import { useEffect, useMemo, useRef, useState } from "react";
import { jalaliMonthLength, toGregorian, toJalali, type JalaliDate } from "../lib/jalali";

const MONTHS = [
  "فروردین",
  "اردیبهشت",
  "خرداد",
  "تیر",
  "مرداد",
  "شهریور",
  "مهر",
  "آبان",
  "آذر",
  "دی",
  "بهمن",
  "اسفند",
];
const WEEKDAYS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];
const persianNumber = new Intl.NumberFormat("fa-IR", { useGrouping: false });
const persianTwoDigitNumber = new Intl.NumberFormat("fa-IR", {
  minimumIntegerDigits: 2,
  useGrouping: false,
});

interface DraftDate extends JalaliDate {
  hour: string;
  minute: string;
}

interface JalaliDatePickerProps {
  value: string;
  onChange: (value: string) => void;
  includeTime?: boolean;
  placeholder?: string;
}

function pad(value: number | string): string {
  return String(value).padStart(2, "0");
}

function latinDigits(value: string): string {
  return value.replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)));
}

function persianDigits(value: string): string {
  return value.replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
}

function todayDraft(): DraftDate {
  const now = new Date();
  return {
    ...toJalali(now.getFullYear(), now.getMonth() + 1, now.getDate()),
    hour: pad(now.getHours()),
    minute: pad(now.getMinutes()),
  };
}

function parseValue(value: string): DraftDate | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(value);
  if (!match) return null;
  return {
    ...toJalali(Number(match[1]), Number(match[2]), Number(match[3])),
    hour: match[4] ?? "00",
    minute: match[5] ?? "00",
  };
}

function displayValue(value: string, includeTime: boolean): string {
  const parsed = parseValue(value);
  if (!parsed) return "";
  const date = `${persianNumber.format(parsed.year)}/${persianNumber.format(parsed.month)}/${persianNumber.format(parsed.day)}`;
  return includeTime
    ? `${date}، ${persianTwoDigitNumber.format(Number(parsed.hour))}:${persianTwoDigitNumber.format(Number(parsed.minute))}`
    : date;
}

export default function JalaliDatePicker({
  value,
  onChange,
  includeTime = false,
  placeholder = "انتخاب تاریخ",
}: JalaliDatePickerProps) {
  const root = useRef<HTMLDivElement>(null);
  const initial = parseValue(value) ?? todayDraft();
  const [open, setOpen] = useState(false);
  const [viewYear, setViewYear] = useState(initial.year);
  const [viewMonth, setViewMonth] = useState(initial.month);
  const [draft, setDraft] = useState<DraftDate>(initial);
  const today = todayDraft();

  useEffect(() => {
    if (!open) return;
    const selected = parseValue(value) ?? todayDraft();
    setDraft(selected);
    setViewYear(selected.year);
    setViewMonth(selected.month);

    function dismiss(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }

    function dismissWithKeyboard(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", dismissWithKeyboard);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", dismissWithKeyboard);
    };
  }, [open, value]);

  const offset = useMemo(() => {
    const first = toGregorian(viewYear, viewMonth, 1);
    return (new Date(first.year, first.month - 1, first.day).getDay() + 1) % 7;
  }, [viewMonth, viewYear]);
  const monthLength = jalaliMonthLength(viewYear, viewMonth);

  function moveMonth(delta: number) {
    const next = viewMonth + delta;
    if (next < 1) {
      setViewYear(viewYear - 1);
      setViewMonth(12);
    } else if (next > 12) {
      setViewYear(viewYear + 1);
      setViewMonth(1);
    } else {
      setViewMonth(next);
    }
  }

  function serialize(next: DraftDate): string {
    const gregorian = toGregorian(next.year, next.month, next.day);
    const date = `${gregorian.year}-${pad(gregorian.month)}-${pad(gregorian.day)}`;
    return includeTime ? `${date}T${pad(next.hour)}:${pad(next.minute)}` : date;
  }

  function chooseDay(day: number) {
    const next = { ...draft, year: viewYear, month: viewMonth, day };
    setDraft(next);
    if (!includeTime) {
      onChange(serialize(next));
      setOpen(false);
    }
  }

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        className="input flex min-h-[42px] w-full items-center justify-between gap-2 bg-white text-right"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={value ? "text-slate-900" : "text-slate-400"}>
          {value ? displayValue(value, includeTime) : placeholder}
        </span>
        <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-slate-400" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z" />
        </svg>
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="انتخاب تاریخ شمسی"
          dir="rtl"
          className="absolute right-0 z-[70] mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-2xl border-2 bg-white"
          style={{ borderColor: "var(--color-primary, #4B6E48)" }}
        >
          <div className="flex items-center justify-between border-b bg-brand-50/80 px-4 py-3" style={{ borderColor: "var(--color-primary, #4B6E48)" }}>
            <button type="button" className="flex h-9 w-9 items-center justify-center rounded-xl border bg-white transition hover:bg-brand-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2" style={{ borderColor: "var(--color-primary, #4B6E48)", color: "var(--color-primary, #4B6E48)", outlineColor: "var(--color-primary, #4B6E48)" }} aria-label="ماه بعد" onClick={() => moveMonth(1)}>
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2"><path d="m9 18 6-6-6-6" /></svg>
            </button>
            <div className="text-base font-extrabold" style={{ color: "var(--color-primary, #4B6E48)" }}>{MONTHS[viewMonth - 1]} {persianNumber.format(viewYear)}</div>
            <button type="button" className="flex h-9 w-9 items-center justify-center rounded-xl border bg-white transition hover:bg-brand-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2" style={{ borderColor: "var(--color-primary, #4B6E48)", color: "var(--color-primary, #4B6E48)", outlineColor: "var(--color-primary, #4B6E48)" }} aria-label="ماه قبل" onClick={() => moveMonth(-1)}>
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2"><path d="m15 18-6-6 6-6" /></svg>
            </button>
          </div>

          <div className="grid grid-cols-7 gap-1 p-4 pt-3 text-center text-xs">
            {WEEKDAYS.map((weekday) => <span key={weekday} className="py-1.5 font-bold text-slate-500">{weekday}</span>)}
            {Array.from({ length: offset }, (_, index) => <span key={`empty-${index}`} />)}
            {Array.from({ length: monthLength }, (_, index) => {
              const day = index + 1;
              const selected = Boolean(value) && draft.year === viewYear && draft.month === viewMonth && draft.day === day;
              const isToday = today.year === viewYear && today.month === viewMonth && today.day === day;
              return (
                <button
                  key={day}
                  type="button"
                  aria-label={`${persianNumber.format(day)} ${MONTHS[viewMonth - 1]} ${persianNumber.format(viewYear)}`}
                  aria-current={isToday ? "date" : undefined}
                  aria-pressed={selected}
                  className={`flex h-10 items-center justify-center rounded-xl text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 ${selected ? "text-white" : isToday ? "border bg-brand-50" : "text-slate-700 hover:bg-brand-50"}`}
                  style={{
                    backgroundColor: selected ? "var(--color-primary, #4B6E48)" : undefined,
                    borderColor: isToday ? "var(--color-primary, #4B6E48)" : undefined,
                    color: selected || isToday ? (selected ? "#FFFFFF" : "var(--color-primary, #4B6E48)") : undefined,
                    outlineColor: "var(--color-primary, #4B6E48)",
                  }}
                  onClick={() => chooseDay(day)}
                >
                  {persianNumber.format(day)}
                </button>
              );
            })}
          </div>

          {includeTime ? (
            <div className="border-t border-brand-200 bg-brand-50/50 px-4 py-3">
              <div className="mb-3 flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-700">ساعت</span>
                <input
                  className="input min-w-0 py-1.5 text-center"
                  type="text"
                  inputMode="numeric"
                  aria-label="ساعت"
                  value={persianDigits(draft.hour)}
                  onChange={(event) => setDraft({ ...draft, hour: latinDigits(event.target.value) })}
                />
                <span className="font-bold" style={{ color: "var(--color-primary, #4B6E48)" }}>:</span>
                <input
                  className="input min-w-0 py-1.5 text-center"
                  type="text"
                  inputMode="numeric"
                  aria-label="دقیقه"
                  value={persianDigits(draft.minute)}
                  onChange={(event) => setDraft({ ...draft, minute: latinDigits(event.target.value) })}
                />
              </div>
              <button
                type="button"
                className="btn w-full"
                style={{ backgroundColor: "var(--color-primary, #4B6E48)" }}
                onClick={() => {
                  const hour = Math.min(23, Math.max(0, Number(draft.hour) || 0));
                  const minute = Math.min(59, Math.max(0, Number(draft.minute) || 0));
                  onChange(serialize({ ...draft, hour: pad(hour), minute: pad(minute) }));
                  setOpen(false);
                }}
              >
                تأیید
              </button>
            </div>
          ) : null}

          {value ? (
            <button
              type="button"
              className="w-full border-t bg-white py-2.5 text-sm font-semibold text-slate-500 transition hover:bg-brand-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px]"
              style={{ borderColor: "var(--color-primary, #4B6E48)", outlineColor: "var(--color-primary, #4B6E48)" }}
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
            >
              پاک کردن تاریخ
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
