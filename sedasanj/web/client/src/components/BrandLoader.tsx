import { useEffect, useRef, useState } from "react";
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

export function RouteLoadingOverlay() {
  const location = useLocation();
  const [visible, setVisible] = useState(true);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    setVisible(true);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setVisible(false), (LOGO_MOTION_DURATION + 0.8) * 1000);

    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [location.key]);

  return (
    <div className={`route-loading-overlay ${visible ? "route-loading-overlay--visible" : ""}`} aria-hidden={!visible}>
      <BrandLoader key={location.key} onComplete={() => {
        if (timerRef.current !== null) window.clearTimeout(timerRef.current);
        timerRef.current = window.setTimeout(() => setVisible(false), 300);
      }} />
    </div>
  );
}
