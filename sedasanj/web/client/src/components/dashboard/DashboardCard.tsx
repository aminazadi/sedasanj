import type { ReactNode } from "react";

/** Card shell shared by every executive dashboard panel: title, one-line hint, optional action. */
export function DashboardCard({ title, hint, action, children, className = "" }: { title: ReactNode; hint?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`card exec-card ${className}`}>
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0"><h2 className="font-bold text-slate-800">{title}</h2>{hint ? <p className="mt-1 text-xs leading-5 text-slate-500">{hint}</p> : null}</div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
    {children}
  </section>;
}

/** Segmented toggle; the caller keeps the value in the URL. */
export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: Array<{ value: T; label: string }>; onChange: (value: T) => void; label: string }) {
  return <div className="exec-segmented" role="group" aria-label={label}>
    {options.map((option) => <button key={option.value} type="button" aria-pressed={option.value === value} onClick={() => onChange(option.value)}>{option.label}</button>)}
  </div>;
}
