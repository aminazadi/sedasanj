import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { artForPath } from "./pageArt";

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  const art = artForPath(useLocation().pathname);
  return (
    <header className="panel-hero">
      {art ? <img className={`panel-hero__art panel-hero__art--${art.fit}`} src={art.src} alt="" aria-hidden="true" decoding="async" /> : null}
      <div className="panel-hero__body">
        <h1 className="text-xl font-black">{title}</h1>
        {description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}
      </div>
      {actions ? <div className="panel-hero__actions">{actions}</div> : null}
    </header>
  );
}
