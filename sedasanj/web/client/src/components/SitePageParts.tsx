import { srcSetFor } from "../lib/imageSources";
import { Icon } from "./SiteIcon";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import aboutArt from "../assets/page-hero-about.webp";
import contactArt from "../assets/page-hero-contact.webp";
import helpArt from "../assets/page-hero-help.webp";
import legalArt from "../assets/page-hero-legal.webp";

/** Internal paths use the router; https/tel/mailto links are plain anchors. */
export function SafeLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  if (href.startsWith("/")) return <Link className={className} to={href}>{children}</Link>;
  const external = href.startsWith("https://");
  return <a className={className} href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{children}</a>;
}

export function PageStatus({ state, onRetry }: { state: "loading" | "error"; onRetry: () => void }) {
  return <main className="page-main"><section className="page-status" role={state === "error" ? "alert" : "status"}>
    {state === "loading" ? <p>در حال بارگذاری…</p> : <><p>بارگذاری این صفحه انجام نشد. اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.</p><button className="site-button site-button-outline" type="button" onClick={onRetry}><Icon name="refresh" size={18}/>تلاش دوباره</button></>}
  </section></main>;
}

const HERO_ART = { about: aboutArt, contact: contactArt, help: helpArt, legal: legalArt } as const;

/** Per-page illustration shown above the heading of a public page hero (see docs/page-illustrations.md). */
export function HeroArt({ page }: { page: keyof typeof HERO_ART }) {
  return <img className="page-hero-art" src={HERO_ART[page]} srcSet={srcSetFor(HERO_ART[page])} sizes="(max-width: 760px) calc(100vw - 48px), 600px" alt="" width="1500" height="750" decoding="async"/>;
}
