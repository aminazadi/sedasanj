import { useId } from "react";
import logoSource from "../assets/sedasanj-refined-master.svg?raw";

const logoPath = logoSource.match(/<path[^>]+\sd="([^"]+)"/)?.[1];

if (!logoPath) {
  throw new Error("Unable to load the Sedasanj logo path.");
}

type BrandLogoProps = {
  animated?: boolean;
  className?: string;
  title?: string;
};

export function BrandLogo({ animated = false, className = "", title }: BrandLogoProps) {
  const clipId = `brand-logo-clip-${useId().replace(/:/g, "")}`;
  const revealDuration = className.includes("panel-brand-logo") ? "4.8s" : "1.45s";

  return (
    <svg className={`brand-logo ${animated ? "brand-logo--animated" : ""} ${className}`.trim()} viewBox="0 0 520 189" role="img" aria-hidden={title ? undefined : true} aria-label={title}>
      {title ? <title>{title}</title> : null}
      <clipPath id={clipId}>
        <rect className="brand-logo__reveal" width="520" height="189" />
      </clipPath>
      <path className="brand-logo__path" d={logoPath} fillRule="evenodd" clipRule="evenodd" clipPath={`url(#${clipId})`} />
      {animated ? <>
        <line className="brand-logo__cursor" x1="520" x2="520" y1="43" y2="146">
          <animate attributeName="x1" values="520;0;0" keyTimes="0;0.76;1" dur={revealDuration} repeatCount="indefinite" />
          <animate attributeName="x2" values="520;0;0" keyTimes="0;0.76;1" dur={revealDuration} repeatCount="indefinite" />
          <animate attributeName="opacity" values="0;1;0;0" keyTimes="0;0.06;0.8;1" dur={revealDuration} repeatCount="indefinite" />
        </line>
        <circle className="brand-logo__cursor-dot" cx="520" cy="94.5" r="4">
          <animate attributeName="cx" values="520;0;0" keyTimes="0;0.76;1" dur={revealDuration} repeatCount="indefinite" />
          <animate attributeName="opacity" values="0;1;0;0" keyTimes="0;0.06;0.8;1" dur={revealDuration} repeatCount="indefinite" />
        </circle>
      </> : null}
    </svg>
  );
}
