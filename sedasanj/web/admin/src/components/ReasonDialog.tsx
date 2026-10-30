import { useCallback, useRef, useState, type ReactNode } from "react";
import { fmt } from "../api";

export interface ReasonResult {
  reason: string;
  days: number | null;
}

interface Options {
  /** Ask for a number of days (1..max) as well as the reason. */
  days?: { label: string; initial: number; max: number };
  confirmLabel?: string;
  destructive?: boolean;
}

/**
 * Asks for the reason (and optionally a day count) behind an admin action, with validation.
 * Usage: `const [ask, dialog] = useReasonDialog();` then `const result = await ask("…"); if (!result) return;`
 * and render `{dialog}`.
 */
export function useReasonDialog(): [(message: string, options?: Options) => Promise<ReasonResult | null>, ReactNode] {
  const [state, setState] = useState<{ message: string; options: Options } | null>(null);
  const [reason, setReason] = useState("");
  const [days, setDays] = useState("");
  const resolver = useRef<((result: ReasonResult | null) => void) | null>(null);

  const ask = useCallback((message: string, options: Options = {}) => {
    setReason("");
    setDays(options.days ? String(options.days.initial) : "");
    setState({ message, options });
    return new Promise<ReasonResult | null>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  function finish(result: ReasonResult | null) {
    setState(null);
    resolver.current?.(result);
    resolver.current = null;
  }

  if (state === null) return [ask, null];
  const limit = state.options.days;
  const dayCount = Number(fmt.latinDigits(days));
  const daysValid = !limit || (Number.isInteger(dayCount) && dayCount >= 1 && dayCount <= limit.max);
  const valid = reason.trim().length >= 3 && daysValid;
  const dialog = (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" role="dialog" aria-modal="true">
      <form
        className="w-full max-w-sm space-y-3 rounded-xl bg-white p-5 shadow-xl"
        onSubmit={(event) => {
          event.preventDefault();
          if (valid) finish({ reason: reason.trim(), days: limit ? dayCount : null });
        }}
      >
        <p className="text-sm text-slate-700">{state.message}</p>
        {limit ? (
          <div>
            <label className="label">{limit.label}</label>
            <input className="input" inputMode="numeric" dir="ltr" value={days} onChange={(event) => setDays(event.target.value)} />
            {!daysValid ? <p className="mt-1 text-xs text-rose-600">عددی بین ۱ و {fmt.int(limit.max)} وارد کنید.</p> : null}
          </div>
        ) : null}
        <div>
          <label className="label">دلیل (حداقل ۳ نویسه)</label>
          <textarea className="input" rows={3} autoFocus value={reason} onChange={(event) => setReason(event.target.value)} />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => finish(null)}>انصراف</button>
          <button type="submit" className={state.options.destructive ? "btn-ghost text-rose-700" : "btn"} disabled={!valid}>
            {state.options.confirmLabel ?? "تأیید"}
          </button>
        </div>
      </form>
    </div>
  );
  return [ask, dialog];
}
