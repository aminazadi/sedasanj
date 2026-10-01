import type { ReactNode } from "react";

function ChevronIcon() {
  return (
    <svg className="h-5 w-5 transition-transform group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export default function TableFilters({ children }: { children: ReactNode }) {
  return (
    <details className="table-filters group card">
      <summary className="table-filters-summary flex cursor-pointer list-none items-center justify-between font-bold md:hidden">
        <span>فیلترها</span>
        <ChevronIcon />
      </summary>
      <div className="table-filters-content mt-4 md:mt-0">{children}</div>
    </details>
  );
}
