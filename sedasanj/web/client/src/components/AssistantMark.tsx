import { useEffect, useId, useRef } from "react";

type TriggerableAnimateElement = SVGAnimateElement & { beginElement?: () => void };

export default function AssistantMark({ className = "h-11 w-11", animated = true }: { className?: string; animated?: boolean }) {
  const uid = useId();
  const svgRef = useRef<SVGSVGElement>(null);
  const faceRef = useRef<SVGGElement>(null);
  const pupilsRef = useRef<SVGPathElement>(null);
  const celebrateTriggerRef = useRef<TriggerableAnimateElement>(null);
  const celebrateTimeoutRef = useRef<number>();

  useEffect(() => {
    if (!animated) return undefined;
    let frame = 0;
    const onMove = (event: PointerEvent) => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const rect = svgRef.current?.getBoundingClientRect();
        if (!rect) return;
        const dx = event.clientX - (rect.left + rect.width / 2);
        const dy = event.clientY - (rect.top + rect.height / 2);
        const dist = Math.hypot(dx, dy) || 1;
        const nx = dx / dist;
        const ny = dy / dist;
        pupilsRef.current?.setAttribute("transform", `translate(${(nx * 2).toFixed(2)} ${(ny * 2.2).toFixed(2)})`);
        faceRef.current?.setAttribute("transform", `translate(${(nx * 1.6).toFixed(2)} ${(ny * 1).toFixed(2)}) rotate(${(nx * 3.5).toFixed(2)} 48 48)`);
      });
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [animated]);

  useEffect(() => () => window.clearTimeout(celebrateTimeoutRef.current), []);

  function celebrate() {
    if (!animated) return;
    const svg = svgRef.current;
    if (!svg) return;
    svg.classList.add("is-celebrating");
    window.clearTimeout(celebrateTimeoutRef.current);
    celebrateTimeoutRef.current = window.setTimeout(() => svg.classList.remove("is-celebrating"), 900);
    celebrateTriggerRef.current?.beginElement?.();
  }

  const shell = `shell-${uid}`;
  const screen = `screen-${uid}`;
  const faceLight = `faceLight-${uid}`;
  const gold = `gold-${uid}`;
  const drop = `drop-${uid}`;
  const celebrateTrigger = `celebrate-${uid}`;

  return (
    <svg ref={svgRef} className={`assistant-mark ${className}`} viewBox="0 0 96 96" fill="none" aria-hidden="true" onClick={animated ? celebrate : undefined}>
      <defs>
        <linearGradient id={shell} x1="23" y1="19" x2="71" y2="76" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--mark-shell-0, #FFF9DD)" />
          <stop offset=".38" stopColor="var(--mark-shell-38, #CFD9B0)" />
          <stop offset=".72" stopColor="var(--mark-shell-72, #8FA77A)" />
          <stop offset="1" stopColor="var(--mark-shell-100, #536F55)" />
        </linearGradient>
        <linearGradient id={screen} x1="31" y1="34" x2="68" y2="67" gradientUnits="userSpaceOnUse">
          <stop stopColor="#243A33" />
          <stop offset="1" stopColor="#101D1A" />
        </linearGradient>
        <linearGradient id={faceLight} x1="35" y1="41" x2="63" y2="59" gradientUnits="userSpaceOnUse">
          <stop stopColor="#B8F1C4" />
          <stop offset="1" stopColor="#64C98C" />
        </linearGradient>
        <linearGradient id={gold} x1="38" y1="65" x2="59" y2="72" gradientUnits="userSpaceOnUse">
          <stop stopColor="#F6D38B" />
          <stop offset="1" stopColor="#D89B50" />
        </linearGradient>
        <filter id={drop} x="11" y="12" width="74" height="82" colorInterpolationFilters="sRGB" filterUnits="userSpaceOnUse">
          <feGaussianBlur stdDeviation="3.5" />
        </filter>
      </defs>
      {animated ? <animate ref={celebrateTriggerRef} id={celebrateTrigger} attributeName="opacity" from="1" to="1" dur="0.01s" begin="indefinite" /> : null}
      <ellipse className="assistant-mark-shadow" cx="48" cy="82" fill="#07120E" fillOpacity=".46" filter={`url(#${drop})`} rx="23" ry="5" />
      <g className="assistant-mark-body">
      <g>
        {animated ? <animateTransform attributeName="transform" type="rotate" values="-7 48 18;7 48 18;-7 48 18" keyTimes="0;.5;1" calcMode="spline" keySplines="0.45 0 0.55 1;0.45 0 0.55 1" dur="1.1s" repeatCount="indefinite" /> : null}
        <path d="M48 10c2.2 0 4 1.8 4 4v4h-8v-4c0-2.2 1.8-4 4-4Z" fill="var(--mark-trim, #C7D3A7)" />
        <g>
          {animated ? <animateTransform attributeName="transform" type="rotate" values="-24 48 10;24 48 10;-24 48 10" keyTimes="0;.5;1" calcMode="spline" keySplines="0.45 0 0.55 1;0.45 0 0.55 1" dur="1.1s" begin="-0.18s" repeatCount="indefinite" /> : null}
          <path d="M48 10V4" stroke="var(--mark-trim, #C7D3A7)" strokeLinecap="round" strokeWidth="3" />
          <path d="M48 9.3V4.7" stroke="var(--mark-trim-highlight, #FFF8D8)" strokeLinecap="round" strokeWidth="1.3" />
          <circle cx="48" cy="3" r="3" fill="#F3C879" stroke="#FFF5D6" strokeWidth="1.5" />
        </g>
      </g>
      <path d="M25 35c0-10 8-18 18-18h10c10 0 18 8 18 18v22c0 9-7 16-16 16H41c-9 0-16-7-16-16V35Z" fill={`url(#${shell})`} stroke="var(--mark-shell-stroke, #FFF8D8)" strokeOpacity="var(--mark-shell-stroke-opacity, .7)" strokeWidth="2" />
      <g ref={faceRef}>
        <path d="M29 36c0-8 6-14 14-14h10c8 0 14 6 14 14v20c0 7-5 12-12 12H41c-7 0-12-5-12-12V36Z" fill={`url(#${screen})`} stroke="#526B50" strokeWidth="2" />
        <g transform="translate(50 46)">
          <g>
            {animated ? <animateTransform attributeName="transform" type="scale" values="1 1;1 1;1 .05;1 1;1 1" keyTimes="0;.68;.705;.73;1" dur="4s" repeatCount="indefinite" /> : null}
            {animated ? <animateTransform attributeName="transform" type="scale" begin={`${celebrateTrigger}.begin`} dur="0.9s" fill="remove" values="1 1;1 .05;1 .05;1 1" keyTimes="0;.16;.78;1" calcMode="spline" keySplines="0.3 0 0.4 1;0 0 1 1;0.3 0 0.4 1" /> : null}
            <g transform="translate(-50 -46)">
              <path d="M35 44c0-2.2 1.8-4 4-4h3v11h-3c-2.2 0-4-1.8-4-4v-3Zm22-4h3c2.2 0 4 1.8 4 4v3c0 2.2-1.8 4-4 4h-3V40Z" fill={`url(#${faceLight})`} />
              <path ref={pupilsRef} d="M40.5 46v.5M59.5 46v.5" stroke="#17342A" strokeLinecap="round" strokeWidth="2.5" />
            </g>
          </g>
        </g>
        <path d="M35 48c2-2 4-2 6 0m14 0c2-2 4-2 6 0" stroke={`url(#${faceLight})`} strokeLinecap="round" strokeWidth="2.5" opacity="0">
          {animated ? <animate attributeName="opacity" begin={`${celebrateTrigger}.begin`} dur="0.9s" fill="remove" values="0;1;1;0" keyTimes="0;.16;.78;1" calcMode="spline" keySplines="0.3 0 0.4 1;0 0 1 1;0.3 0 0.4 1" /> : null}
        </path>
        <path d="M40 58.5c2 0 4.7 0 8 0s6 0 8 0" stroke={`url(#${gold})`} strokeLinecap="round" strokeWidth="2.5">
          {animated ? <animate attributeName="d" values="M40 58.5c2 0 4.7 0 8 0s6 0 8 0;M40 58.5c2 0 4.7 0 8 0s6 0 8 0;M40 57c2 2.3 4.7 3.5 8 3.5s6-1.2 8-3.5;M39 56c2.2 4.3 5.2 6 9 6s6.8-1.7 9-6;M40 57c2 2.3 4.7 3.5 8 3.5s6-1.2 8-3.5;M40 58.5c2 0 4.7 0 8 0s6 0 8 0;M40 58.5c2 0 4.7 0 8 0s6 0 8 0" keyTimes="0;.14;.32;.5;.68;.86;1" calcMode="spline" keySplines="0.42 0 0.58 1;0.42 0 0.58 1;0.42 0 0.58 1;0.42 0 0.58 1;0.42 0 0.58 1;0.42 0 0.58 1" dur="6s" repeatCount="indefinite" /> : null}
          {animated ? <animate attributeName="opacity" begin={`${celebrateTrigger}.begin`} dur="0.9s" fill="remove" values="1;0;0;1" keyTimes="0;.16;.78;1" /> : null}
        </path>
        <g transform="translate(48 62)">
          <g transform="scale(0)">
            {animated ? <animateTransform attributeName="transform" type="scale" begin={`${celebrateTrigger}.begin`} dur="0.9s" fill="remove" values="0;1.2;.85;1.15;.9;1.05;1;0" keyTimes="0;.16;.3;.46;.6;.74;.86;1" calcMode="spline" keySplines="0.3 0 0.4 1;0.3 0 0.4 1;0.3 0 0.4 1;0.3 0 0.4 1;0.3 0 0.4 1;0.3 0 0.4 1;0.3 0 0.4 1" /> : null}
            <g transform="translate(-48 -62)">
              <ellipse cx="48" cy="62" rx="9" ry="6.4" fill={`url(#${screen})`} stroke={`url(#${gold})`} strokeWidth="2" />
              <path d="M41.5 63.5c2 2.4 4.5 3.6 6.5 3.6s4.5-1.2 6.5-3.6" stroke="#FFF3C9" strokeLinecap="round" strokeWidth="1.6" opacity=".85" />
            </g>
          </g>
        </g>
      </g>
      <path d="M24 38h-4c-2.2 0-4 1.8-4 4v8c0 2.2 1.8 4 4 4h4m48-16h4c2.2 0 4 1.8 4 4v8c0 2.2-1.8 4-4 4h-4" fill={`url(#${shell})`} stroke="var(--mark-arm-stroke, #EAF0CE)" strokeWidth="2" />
      <path d="M20 43v6m56-6v6" stroke="#4F6B50" strokeLinecap="round" strokeWidth="2" />
      <path d="M39 72v5m18-5v5" stroke="var(--mark-leg-detail-1, #D8E0BB)" strokeLinecap="round" strokeWidth="3" />
      <path d="M34 79c3-2 8-3 14-3s11 1 14 3" stroke="var(--mark-leg-detail-2, #D7E0B8)" strokeLinecap="round" strokeWidth="2" />
      <g className="assistant-mark-sparkle assistant-mark-sparkle-1" transform="translate(18 26)"><path d="M0-4.2 1.1-1.1 4.2 0 1.1 1.1 0 4.2-1.1 1.1-4.2 0-1.1-1.1Z" fill="#F6D38B" /></g>
      <g className="assistant-mark-sparkle assistant-mark-sparkle-2" transform="translate(78 24) scale(.8)"><path d="M0-4.2 1.1-1.1 4.2 0 1.1 1.1 0 4.2-1.1 1.1-4.2 0-1.1-1.1Z" fill="#B8F1C4" /></g>
      <g className="assistant-mark-sparkle assistant-mark-sparkle-3" transform="translate(12 58) scale(.7)"><path d="M0-4.2 1.1-1.1 4.2 0 1.1 1.1 0 4.2-1.1 1.1-4.2 0-1.1-1.1Z" fill="var(--mark-shell-0, #FFF9DD)" /></g>
      <g className="assistant-mark-sparkle assistant-mark-sparkle-4" transform="translate(84 58) scale(.9)"><path d="M0-4.2 1.1-1.1 4.2 0 1.1 1.1 0 4.2-1.1 1.1-4.2 0-1.1-1.1Z" fill="#F6D38B" /></g>
      <g className="assistant-mark-sparkle assistant-mark-sparkle-5" transform="translate(48 90) scale(.75)"><path d="M0-4.2 1.1-1.1 4.2 0 1.1 1.1 0 4.2-1.1 1.1-4.2 0-1.1-1.1Z" fill="#B8F1C4" /></g>
      </g>
    </svg>
  );
}
