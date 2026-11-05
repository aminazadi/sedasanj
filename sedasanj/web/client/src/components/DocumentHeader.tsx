import type { ReactNode } from "react";

export default function DocumentHeader({ title, metadata, status, actions, children }: {
  title: string;
  metadata: ReactNode;
  status?: ReactNode;
  actions: ReactNode;
  children?: ReactNode;
}) {
  return <section className="call-detail-hero document-header card relative overflow-visible !p-0">
    <div className="absolute inset-x-0 top-0 h-1 bg-[#4B6E48]" />
    <div className="p-4 sm:p-5">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div className="min-w-0">
          <div className="mb-3 flex items-center gap-3">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center bg-[#F2F0EF] text-[#4B6E48]" aria-hidden="true">
              <svg className="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M5 3h10l4 4v14H5V3Z M14 3v5h5M8 12h8M8 16h8" /></svg>
            </span>
            <h1 className="break-words text-xl font-semibold sm:text-2xl">{title}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">{status}{metadata}</div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      </div>
      {children}
    </div>
  </section>;
}
