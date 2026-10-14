import type { ReactNode } from "react";

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return <header className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-xl font-black">{title}</h1>{description ? <p className="mt-1 text-sm text-slate-500">{description}</p> : null}</div>{actions}</header>;
}
