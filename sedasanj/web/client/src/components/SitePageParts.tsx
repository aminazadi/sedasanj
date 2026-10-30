import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import heroArt from "../assets/page-hero-office.webp";

/** Internal paths use the router; https/tel/mailto links are plain anchors. */
export function SafeLink({ href, className, children }: { href: string; className?: string; children: ReactNode }) {
  if (href.startsWith("/")) return <Link className={className} to={href}>{children}</Link>;
  const external = href.startsWith("https://");
  return <a className={className} href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{children}</a>;
}

export function PageStatus({ state, onRetry }: { state: "loading" | "error"; onRetry: () => void }) {
  return <main className="page-main"><section className="page-status" role={state === "error" ? "alert" : "status"}>
    {state === "loading" ? <p>در حال بارگذاری…</p> : <><p>بارگذاری این صفحه انجام نشد. اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.</p><button className="site-button site-button-outline" type="button" onClick={onRetry}>تلاش دوباره</button></>}
  </section></main>;
}

/** Office illustration shown above the heading of every public page hero. */
export function HeroArt() {
  return <img className="page-hero-art" src={heroArt} alt="" width="1500" height="750" decoding="async"/>;
}
