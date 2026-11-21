import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { getStepsForRole, markTourCompleted, type GuideTourStep } from "../lib/guideTourState.mjs";
import { GUIDE_TOUR_STEPS } from "../lib/guideTourSteps";

const CARD_WIDTH = 320;
const CARD_MARGIN = 12;
const DIM_COLOR = "rgba(15,23,42,0.68)";
// A fixed, always-bright color (not a theme variable): the thing it has to contrast against is the
// sidebar's own permanently dark-green chrome, in both light and dark page themes alike.
const RING_COLOR = "#F2F0EF";

// The app resets `box-shadow` to `none !important` globally (its own flat, shadow-free design system),
// so the usual "9999px spread" spotlight trick silently does nothing. Four plain dimming bands around
// the hole, plus a bordered ring, use only `background`/`border` and so are unaffected by that reset.
function Spotlight({ rect }: { rect: DOMRect | null }) {
  if (!rect) {
    return <div aria-hidden="true" className="absolute inset-0 transition-opacity duration-200" style={{ background: DIM_COLOR }} />;
  }
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const pad = 6;
  const top = Math.max(0, rect.top - pad);
  const left = Math.max(0, rect.left - pad);
  const right = Math.min(vw, rect.right + pad);
  const bottom = Math.min(vh, rect.bottom + pad);
  const bands: CSSProperties[] = [
    { top: 0, left: 0, width: vw, height: top },
    { top: bottom, left: 0, width: vw, height: Math.max(0, vh - bottom) },
    { top, left: 0, width: left, height: bottom - top },
    { top, left: right, width: Math.max(0, vw - right), height: bottom - top },
  ];
  return (
    <>
      {bands.map((style, index) => (
        <div key={index} aria-hidden="true" className="absolute transition-[top,left,width,height] duration-200" style={{ ...style, background: DIM_COLOR }} />
      ))}
      <div
        aria-hidden="true"
        className="absolute transition-[top,left,width,height] duration-200"
        style={{ top, left, width: right - left, height: bottom - top, border: `3px solid ${RING_COLOR}`, boxSizing: "border-box" }}
      />
    </>
  );
}

// `offsetParent` is null only behind a real `display:none` ancestor (the collapsed desktop-vs-mobile
// sidebar duplicate), unlike a plain bounding-rect check, which a closed accordion group would also
// zero out even though the item is still a valid, revealable target (see revealTarget below).
function findVisibleTarget(target: string): HTMLElement | null {
  const candidates = document.querySelectorAll<HTMLElement>(`[data-tour-target="${target}"]`);
  for (const candidate of candidates) {
    if (candidate.offsetParent !== null) return candidate;
  }
  return null;
}

// Opens the target's accordion group if it is collapsed, and scrolls it into view within the sidebar's
// own scroll area, before the step is shown as resolved.
function revealTarget(target: HTMLElement) {
  const panel = target.closest<HTMLElement>(".sidebar-group-panel");
  if (panel && panel.dataset.open === "false") {
    document.querySelector<HTMLButtonElement>(`button[aria-controls="${panel.id}"]`)?.click();
  }
  target.scrollIntoView({ block: "nearest" });
}

interface GuideTourProps {
  active: boolean;
  role: string;
  onFinish: () => void;
}

export default function GuideTour({ active, role, onFinish }: GuideTourProps) {
  const steps = getStepsForRole(GUIDE_TOUR_STEPS, role);
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [resolved, setResolved] = useState(false);
  const titleId = useId();
  const bodyId = useId();
  const primaryRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (active) setStepIndex(0);
  }, [active]);

  const step: GuideTourStep | undefined = steps[stepIndex];

  const finish = () => {
    markTourCompleted(role, window.localStorage);
    onFinish();
  };

  // A step whose target never mounts (hidden by a permission, or removed later) is skipped rather than
  // shown empty — but only after giving layout a chance to settle first: right after the previous step's
  // `revealTarget` (an accordion toggle, a scroll), the very next frame can transiently report the new
  // target as not found before its own group/scroll position has caught up, so this polls for a few
  // frames rather than deciding on the first one.
  useEffect(() => {
    if (!active || !step) return;
    setResolved(false);
    if (step.target === null) {
      setResolved(true);
      return;
    }
    // A wall-clock budget, not a frame count: a backgrounded/throttled tab can take far longer than
    // 20 frames to reach this many milliseconds, and should still get the same chance to settle.
    const BUDGET_MS = 1500;
    const startedAt = performance.now();
    let frame = 0;
    const tryResolve = () => {
      const target = findVisibleTarget(step.target as string);
      if (target) {
        revealTarget(target);
        setResolved(true);
        return;
      }
      if (performance.now() - startedAt >= BUDGET_MS) {
        if (stepIndex < steps.length - 1) setStepIndex((current) => current + 1);
        else finish();
        return;
      }
      frame = window.requestAnimationFrame(tryResolve);
    };
    frame = window.requestAnimationFrame(tryResolve);
    return () => window.cancelAnimationFrame(frame);
  }, [active, step, stepIndex, steps.length]);

  useLayoutEffect(() => {
    if (!active || !step || !resolved || step.target === null) {
      setRect(null);
      return;
    }
    let frame = 0;
    const measure = () => {
      const target = findVisibleTarget(step.target as string);
      if (!target) {
        setRect(null);
        return;
      }
      setRect(target.getBoundingClientRect());
      frame = window.requestAnimationFrame(measure);
    };
    measure();
    return () => window.cancelAnimationFrame(frame);
  }, [active, step, resolved]);

  useEffect(() => {
    if (!active || !resolved) return;
    primaryRef.current?.focus();
  }, [active, resolved, stepIndex]);

  useEffect(() => {
    if (!active) return;
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") finish();
    };
    window.addEventListener("keydown", dismiss);
    return () => window.removeEventListener("keydown", dismiss);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, role]);

  if (!active || !step || !resolved) return null;

  const isLast = stepIndex === steps.length - 1;
  // A card anchored to the target's start side only fits when there is actually room for it there —
  // on a narrow (mobile) viewport the sidebar drawer itself can fill most of the width, leaving none;
  // in that case fall back to the same centered presentation the no-target "welcome" step already uses.
  const cardWidth = Math.min(CARD_WIDTH, window.innerWidth - CARD_MARGIN * 2);
  const canAnchor = !!rect && rect.left >= cardWidth + CARD_MARGIN * 2;
  const cardStyle: CSSProperties = canAnchor && rect
    ? {
        top: Math.max(CARD_MARGIN, Math.min(rect.top + rect.height / 2 - 120, window.innerHeight - 240 - CARD_MARGIN)),
        right: window.innerWidth - rect.left + CARD_MARGIN,
        width: cardWidth,
      }
    : { width: cardWidth };

  return (
    <div className="fixed inset-0 z-[110]">
      <Spotlight rect={rect} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        dir="rtl"
        className={`pointer-events-auto fixed border border-[color:var(--line)] bg-[var(--color-canvas)] p-5 shadow-2xl ${canAnchor ? "" : "left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"}`}
        style={cardStyle}
      >
        <p className="text-xs font-medium text-[var(--color-neutral)]">
          مرحله {stepIndex + 1} از {steps.length}
        </p>
        <h2 id={titleId} className="mt-1 text-base font-bold text-[color:var(--ink)]">
          {step.title}
        </h2>
        <p id={bodyId} aria-live="polite" className="mt-2 text-sm leading-7 text-[var(--color-neutral)]">
          {step.body}
        </p>
        <div className="mt-4 flex items-center justify-between gap-2">
          <button type="button" className="text-xs text-[var(--color-neutral)] underline-offset-2 hover:underline" onClick={finish}>
            رد کردن راهنما
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              className="min-h-9 border border-[color:var(--line)] px-3 text-sm font-bold text-[color:var(--ink)] transition hover:bg-[var(--color-canvas)] disabled:cursor-not-allowed disabled:opacity-50"
              disabled={stepIndex === 0}
              onClick={() => setStepIndex((current) => Math.max(0, current - 1))}
            >
              قبلی
            </button>
            <button
              ref={primaryRef}
              type="button"
              className="min-h-9 bg-[var(--color-primary)] px-4 text-sm font-bold text-white transition hover:bg-[#3F5D3D]"
              onClick={() => (isLast ? finish() : setStepIndex((current) => current + 1))}
            >
              {isLast ? "پایان" : "بعدی"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
