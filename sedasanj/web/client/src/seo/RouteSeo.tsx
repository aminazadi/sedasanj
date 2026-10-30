import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { applySeo, siteUrl } from "./head";
import { findRoute, privateSeo, routeSeo } from "./siteSeo";

/**
 * Applies the hard-coded SEO metadata for the current URL. Mounted once, above the router outlet.
 * Pages with their own metadata (help articles) call `useArticleSeo`, which runs after this effect.
 */
export default function RouteSeo() {
  const { pathname } = useLocation();
  const { session } = useAuth();
  useEffect(() => {
    const route = findRoute(pathname);
    const dashboardHome = pathname === "/" && session;
    if (pathname.startsWith("/help/") && !pathname.startsWith("/help/errors/")) return;
    if (route && !dashboardHome) applySeo(routeSeo(route, siteUrl()));
    else applySeo(privateSeo(pathname));
  }, [pathname, session]);
  return null;
}
