import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const initial = parseValue(value) ?? todayDraft();
  const [open, setOpen] = useState(false);
  const [viewYear, setViewYear] = useState(initial.year);
  const [viewMonth, setViewMonth] = useState(initial.month);
  const [draft, setDraft] = useState<DraftDate>(initial);
  const [panelPosition, setPanelPosition] = useState({ top: 0, left: 0, width: 352 });
  const today = todayDraft();

  const positionPanel = useCallback(() => {
    if (!trigger.current) return;
    const rect = trigger.current.getBoundingClientRect();
    const viewportPadding = 8;
    const width = Math.min(352, window.innerWidth - viewportPadding * 2);
    const height = panel.current?.offsetHeight ?? (includeTime ? 540 : 440);
    const spaceBelow = window.innerHeight - rect.bottom - viewportPadding;
    const top = spaceBelow >= height || spaceBelow >= rect.top
      ? Math.min(rect.bottom + 8, window.innerHeight - height - viewportPadding)
      : Math.max(viewportPadding, rect.top - height - 8);
    const left = Math.min(
      window.innerWidth - width - viewportPadding,
      Math.max(viewportPadding, rect.right - width),
    );
    setPanelPosition({ top: Math.max(viewportPadding, top), left, width });
  }, [includeTime]);

  useEffect(() => {
    if (!open) return;
    const selected = parseValue(value) ?? todayDraft();
    setDraft(selected);
    setViewYear(selected.year);
    setViewMonth(selected.month);

    function dismiss(event: MouseEvent) {
      const target = event.target as Node;
      if (!root.current?.contains(target) && !panel.current?.contains(target)) setOpen(false);
    }

    function dismissWithKeyboard(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", dismissWithKeyboard);
    window.addEventListener("resize", positionPanel);
    window.addEventListener("scroll", positionPanel, true);
    positionPanel();
    const frame = window.requestAnimationFrame(positionPanel);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", dismissWithKeyboard);
      window.removeEventListener("resize", positionPanel);
      window.removeEventListener("scroll", positionPanel, true);
      window.cancelAnimationFrame(frame);
    };
  }, [open, positionPanel, value]);

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
        ref={trigger}
        type="button"
        className="input flex min-h-[42px] w-full items-center justify-between gap-2 bg-white text-right"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={value ? "text-[#4B6E48]" : "text-[#898989]"}>
          {value ? displayValue(value, includeTime) : placeholder}
        </span>
        <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-[#898989]" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z" />
        </svg>
      </button>

      {open ? createPortal(
        <div
          ref={panel}
          role="dialog"
          aria-label="انتخاب تاریخ شمسی"
          dir="rtl"
          className="fixed z-[10000] max-h-[calc(100vh-1rem)] overflow-y-auto rounded-2xl border border-[#B2AC88] bg-[#F2F0EF] shadow-2xl"
          style={{ top: panelPosition.top, left: panelPosition.left, width: panelPosition.width }}
        >
          <div className="flex items-center justify-between border-b border-[#B2AC88] bg-[#F2F0EF] px-4 py-3">
            <button type="button" className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#B2AC88] bg-[#F2F0EF] text-[#4B6E48] outline-none transition hover:bg-[#4B6E48] hover:text-[#F2F0EF] focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]" aria-label="ماه بعد" onClick={() => moveMonth(1)}>
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2"><path d="m9 18 6-6-6-6" /></svg>
            </button>
            <div className="text-base font-extrabold text-[#4B6E48]">{MONTHS[viewMonth - 1]} {persianNumber.format(viewYear)}</div>
            <button type="button" className="flex h-9 w-9 items-center justify-center rounded-xl border border-[#B2AC88] bg-[#F2F0EF] text-[#4B6E48] outline-none transition hover:bg-[#4B6E48] hover:text-[#F2F0EF] focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]" aria-label="ماه قبل" onClick={() => moveMonth(-1)}>
              <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2"><path d="m15 18-6-6 6-6" /></svg>
            </button>
          </div>

          <div className="grid grid-cols-7 gap-1 p-4 pt-3 text-center text-xs">
            {WEEKDAYS.map((weekday) => <span key={weekday} className="py-1.5 font-bold text-[#898989]">{weekday}</span>)}
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
                  className={`flex h-10 items-center justify-center rounded-xl text-sm font-semibold outline-none transition hover:bg-[#4B6E48] hover:text-[#F2F0EF] focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[#4B6E48] ${selected ? "bg-[#4B6E48] text-[#F2F0EF]" : isToday ? "border border-[#4B6E48] text-[#4B6E48]" : "text-[#4B6E48]"}`}
                  onClick={() => chooseDay(day)}
                >
                  {persianNumber.format(day)}
                </button>
              );
            })}
          </div>

          {includeTime ? (
            <div className="border-t border-[#B2AC88] bg-[#F2F0EF] px-4 py-3">
              <div className="mb-3 flex items-center gap-2">
                <span className="text-sm font-semibold text-[#4B6E48]">ساعت</span>
                <input
                  className="input min-w-0 py-1.5 text-center"
                  type="text"
                  inputMode="numeric"
                  aria-label="ساعت"
                  value={persianDigits(draft.hour)}
                  onChange={(event) => setDraft({ ...draft, hour: latinDigits(event.target.value) })}
                />
                <span className="font-bold text-[#4B6E48]">:</span>
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
                className="w-full bg-[#4B6E48] px-4 py-2 text-[#F2F0EF] outline-none transition hover:bg-[#3F5D3D] focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:opacity-50"
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
              className="w-full border-t border-[#B2AC88] bg-[#F2F0EF] py-2.5 text-sm font-semibold text-[#898989] outline-none transition hover:bg-[#4B6E48] hover:text-[#F2F0EF] focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#4B6E48]"
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
            >
              پاک کردن تاریخ
            </button>
          ) : null}
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
