import { useId, useLayoutEffect, useRef, useState } from "react";
import logoSource from "../assets/sedasanj-refined-master.svg?raw";
import { createLogoMotion, LOGO_MOTION_DURATION, PEN_STROKES } from "./logo-motion";

const logoPath = logoSource.match(/<path[^>]+\sd="([^"]+)"/)?.[1];
const contours = logoPath?.match(/M[^M]+/g);
if (!contours || contours.length !== 6) throw new Error("Invalid Sedasanj logo geometry.");
const bodyPath = [contours[1], contours[2], contours[3], contours[5]].join(" ");
const topDotPath = contours[4];
const bottomDotPath = contours[0];

type BrandLogoProps = {
  animated?: boolean;
  className?: string;
  title?: string;
  color?: string;
  duration?: number;
  onComplete?: () => void;
};

export function BrandLogo({ animated = false, className = "", title, color = "#101113", duration = LOGO_MOTION_DURATION, onComplete }: BrandLogoProps) {
  const id = `brand-${useId().replace(/:/g, "")}`;
  const svgRef = useRef<SVGSVGElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const completeRef = useRef(onComplete);
  const finishedRef = useRef(false);
  const [replay, setReplay] = useState(0);
  completeRef.current = onComplete;

  useLayoutEffect(() => {
    if (!animated || !svgRef.current || !canvasRef.current) return;
    const svg = svgRef.current;
    const canvas = canvasRef.current;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    let dispose: (() => void) | undefined;
    const start = () => {
      dispose?.();
      finishedRef.current = false;
      if (media.matches) {
        svg.querySelectorAll<SVGPathElement>("[data-pen-stroke]").forEach((path, index) => {
          path.style.strokeDashoffset = "0";
          path.style.strokeWidth = `${PEN_STROKES[index].width}`;
        });
        svg.querySelector<SVGRectElement>("[data-mask-finish]")!.style.opacity = "1";
        finishedRef.current = true;
        completeRef.current?.();
      } else {
        dispose = createLogoMotion(svg, canvas, Math.max(duration, 0.5), () => {
          finishedRef.current = true;
          completeRef.current?.();
        });
      }
    };
    start();
    media.addEventListener("change", start);
    return () => { dispose?.(); media.removeEventListener("change", start); };
  }, [animated, duration, replay]);

  const mask = (name: string) => animated ? `url(#${id}-${name})` : undefined;
  return (
    <span className={`brand-logo ${className}`.trim()} style={{ color }} onPointerEnter={event => {
      if (animated && event.pointerType === "mouse" && finishedRef.current && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        finishedRef.current = false;
        setReplay(value => value + 1);
      }
    }}>
      <svg ref={svgRef} viewBox="0 0 520 189" role="img" aria-hidden={title ? undefined : true} aria-label={title}>
        {title ? <title>{title}</title> : null}
        {animated ? <defs>
          {PEN_STROKES.map(stroke => <clipPath id={`${id}-${stroke.name}-clip`} key={stroke.name}><path d={stroke.clip} /></clipPath>)}
          {["body", "top", "bottom"].map((part, groupIndex) => (
            <mask id={`${id}-${part}`} key={part} x="0" y="0" width="520" height="189" maskUnits="userSpaceOnUse" style={{ maskType: "luminance" }}>
              {PEN_STROKES.filter(stroke => groupIndex === 0 ? !("dot" in stroke) : stroke.name === (groupIndex === 1 ? "nun-dot" : "jim-dot")).map(stroke => (
                <path key={stroke.name} data-pen-stroke={stroke.name} d={stroke.path} clipPath={`url(#${id}-${stroke.name}-clip)`} fill="none" stroke="white" strokeWidth={stroke.width} strokeLinecap="round" strokeLinejoin="round" />
              ))}
              {groupIndex === 0 ? <rect data-mask-finish width="520" height="189" fill="white" opacity="0" /> : null}
            </mask>
          ))}
        </defs> : null}
        <path data-logo-artwork d={bodyPath} fill="currentColor" fillRule="evenodd" mask={mask("body")} />
        <path d={topDotPath} fill="currentColor" mask={mask("top")} />
        <path d={bottomDotPath} fill="currentColor" mask={mask("bottom")} />
      </svg>
      {animated ? <canvas ref={canvasRef} className="brand-logo__canvas" aria-hidden="true" /> : null}
    </span>
  );
}
