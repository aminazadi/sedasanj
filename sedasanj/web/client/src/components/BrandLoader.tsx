import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { BrandLogo } from "./BrandLogo";

type BrandLoaderProps = {
  compact?: boolean;
  label?: string;
};

export function BrandLoader({ compact = false, label = "در حال بارگذاری" }: BrandLoaderProps) {
  return (
    <div className={`brand-loader ${compact ? "brand-loader--compact" : ""}`} role="status" aria-live="polite">
      <span className="brand-loader__halo" aria-hidden="true" />
      <BrandLogo animated className="brand-loader__logo" />
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
    timerRef.current = window.setTimeout(() => setVisible(false), 620);

    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [location.key]);

  return (
    <div className={`route-loading-overlay ${visible ? "route-loading-overlay--visible" : ""}`} aria-hidden={!visible}>
      <BrandLoader />
    </div>
  );
}
