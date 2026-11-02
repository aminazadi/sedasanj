import type { ReactNode } from "react";
import { EMPTY_STATE_ART } from "./pageArt";

/** Shared empty state: illustration, bold title, one-line description and an optional action. */
export function PanelEmpty({ art = EMPTY_STATE_ART, title, description, children }: { art?: string; title: string; description?: ReactNode; children?: ReactNode }) {
  return <div className="panel-empty">
    <img className="panel-empty__art" src={art} alt="" aria-hidden="true" loading="lazy" decoding="async" />
    <strong className="text-sm text-slate-700">{title}</strong>
    {description ? <p className="mt-1 max-w-xs text-xs leading-6 text-slate-500">{description}</p> : null}
    {children}
  </div>;
}
