import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { BrandLogo } from "./BrandLogo";
import { LOGO_MOTION_DURATION } from "./logo-motion";

type BrandLoaderProps = {
  compact?: boolean;
  label?: string;
  onComplete?: () => void;
};

export function BrandLoader({ compact = false, label = "در حال بارگذاری", onComplete }: BrandLoaderProps) {
  return (
    <div className={`brand-loader ${compact ? "brand-loader--compact" : ""}`} role="status" aria-live="polite">
      <BrandLogo animated className="brand-loader__logo" onComplete={onComplete} />
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function RouteLoadingOverlay({ onComplete }: { onComplete?: () => void }) {
  const location = useLocation();
  const [visible, setVisible] = useState(true);
  const timerRef = useRef<number | null>(null);
  const finishLoading = () => {
    setVisible(false);
    onComplete?.();
  };

  useLayoutEffect(() => {
    setVisible(true);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(finishLoading, (LOGO_MOTION_DURATION + 0.8) * 1000);

    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [location.key]);

  return (
    <div className={`route-loading-overlay ${visible ? "route-loading-overlay--visible" : ""}`} aria-hidden={!visible}>
      <BrandLoader key={location.key} onComplete={() => {
        if (timerRef.current !== null) window.clearTimeout(timerRef.current);
        timerRef.current = window.setTimeout(() => {
          finishLoading();
        }, 300);
      }} />
    </div>
  );
}

export function RouteLoadingGate({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [contentVisible, setContentVisible] = useState(false);

  useLayoutEffect(() => {
    setContentVisible(false);
  }, [location.key]);

  return (
    <>
      <RouteLoadingOverlay onComplete={() => setContentVisible(true)} />
      {contentVisible ? children : null}
    </>
  );
}
