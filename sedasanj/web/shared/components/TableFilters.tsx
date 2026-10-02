import { useEffect, useState, type SyntheticEvent, type ReactNode } from "react";

function ChevronIcon() {
  return (
    <svg className="h-5 w-5 transition-transform group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export default function TableFilters({ children }: { children: ReactNode }) {
  const [isDesktop, setIsDesktop] = useState(() => typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 768px)");
    const handleChange = (event: MediaQueryListEvent) => setIsDesktop(event.matches);

    setIsDesktop(mediaQuery.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  const handleToggle = (event: SyntheticEvent<HTMLDetailsElement>) => {
    if (!isDesktop) setIsMobileOpen(event.currentTarget.open);
  };

  return (
    <details className="table-filters group card" open={isDesktop || isMobileOpen} onToggle={handleToggle}>
      <summary className="table-filters-summary flex cursor-pointer list-none items-center justify-between font-bold md:hidden">
        <span>فیلترها</span>
        <ChevronIcon />
      </summary>
      <div className="table-filters-content mt-4 md:mt-0">{children}</div>
    </details>
  );
}
