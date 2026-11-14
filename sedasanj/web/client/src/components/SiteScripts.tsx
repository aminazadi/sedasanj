import { appendSiteScripts, type ScriptManifest } from "../lib/siteScripts.mjs";
import { useEffect, useRef } from "react";
import { useAuth } from "../auth";
import { request } from "../api";

// Keep execution document-scoped, including React StrictMode's effect replay.
let activeScope: string | null = null;
let started = false;

export default function SiteScripts() {
  const { session, loading } = useAuth();
  const scope = session ? "customer" : "public";
  const mounted = useRef(false);
  useEffect(() => {
    if (loading) return;
    if (activeScope && activeScope !== scope && started) {
      window.location.reload();
      return;
    }
    activeScope = scope;
    mounted.current = true;
    let cancelled = false;
    void request<ScriptManifest>(`/v1/site/scripts/${scope}`)
      .then(async manifest => {
        if (cancelled || started) return;
        started = true;
        await appendSiteScripts(manifest, scope, {
          document,
          isActive: () => mounted.current && activeScope === scope,
          reportFailure: () => console.warn("Site script failed to load; check the configured URL and browser CSP report, then reload."),
        });
      }).catch(() => console.warn("Site scripts could not be loaded; reload the page to retry."));
    return () => { cancelled = true; mounted.current = false; };
  }, [loading, scope]);
  return null;
}
