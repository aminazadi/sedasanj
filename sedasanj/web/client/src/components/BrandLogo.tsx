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
  return (
    <svg className={`brand-logo ${animated ? "brand-logo--animated" : ""} ${className}`.trim()} viewBox="0 0 520 189" role="img" aria-hidden={title ? undefined : true} aria-label={title}>
      {title ? <title>{title}</title> : null}
      <path className="brand-logo__path" d={logoPath} fillRule="evenodd" clipRule="evenodd" pathLength="1" />
    </svg>
  );
}
