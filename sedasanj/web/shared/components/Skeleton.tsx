import type { CSSProperties, ReactNode } from "react";

/** Widths of consecutive rows cycle through these factors so a column does not look stamped. */
const ROW_WIDTHS = [1, 0.82, 0.94, 0.7];

export function Skeleton({ className = "", style }: { className?: string; style?: CSSProperties }) {
  return <span className={`skeleton ${className}`} style={style} aria-hidden="true" />;
}

/**
 * Announces a loading region once. It renders no wrapper element, so siblings keep their parent's
 * spacing (space-y, grid gaps); the placeholders themselves are aria-hidden.
 */
export function SkeletonRegion({ label = "در حال بارگذاری", children }: { label?: string; children: ReactNode }) {
  return (
    <>
      <span className="sr-only" role="status">{label}</span>
      {children}
    </>
  );
}

export type SkeletonCellKind = "text" | "badge" | "badges" | "button";

export interface SkeletonColumn {
  /** Real header content: headers are never skeletons, so they match the loaded table. */
  label?: ReactNode;
  kind?: SkeletonCellKind;
  /** Width of the bar in a first row, any CSS length (text cells only). */
  width?: string;
  /** Overrides the 20px line height, e.g. for a select or input in the cell. */
  height?: string;
  dir?: "ltr" | "rtl";
  /** Classes of the real cell (e.g. max-w-sm truncate), so the column sizes alike. */
  cellClassName?: string;
  ariaLabel?: string;
}

function SkeletonCell({ column, row }: { column: SkeletonColumn; row: number }) {
  const kind = column.kind ?? "text";
  if (kind === "button") return <Skeleton className="skeleton--button" />;
  if (kind === "badge") return <Skeleton className="skeleton--badge" />;
  if (kind === "badges") {
    return (
      <span className="flex items-center gap-1">
        <Skeleton className="skeleton--badge" />
        <Skeleton className="skeleton--badge" style={{ width: "3.5rem" }} />
      </span>
    );
  }
  const factor = ROW_WIDTHS[row % ROW_WIDTHS.length];
  return <Skeleton className="skeleton--line" style={{ width: `calc(${column.width ?? "6rem"} * ${factor})`, height: column.height }} />;
}

/** The real `.table` markup with real headers and placeholder rows, so heights and zebra rows match. */
export function SkeletonTable({ columns, rows, label, className = "" }: { columns: SkeletonColumn[]; rows: number; label?: string; className?: string }) {
  return (
    <SkeletonRegion label={label}>
      <table className={`table ${className}`} dir="rtl" aria-hidden="true">
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th key={index} aria-label={column.ariaLabel}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }, (_, row) => (
            <tr key={row}>
              {columns.map((column, index) => (
                <td key={index} dir={column.dir} className={column.cellClassName}>
                  <SkeletonCell column={column} row={row} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </SkeletonRegion>
  );
}

/** Same chrome as `Stat` (title line, 40px icon slot, 32px value line, optional hint line). */
export function SkeletonStatCard({ hint = false }: { hint?: boolean }) {
  return (
    <div className="panel-stat-card card py-3" aria-hidden="true">
      <div className="relative z-10 mb-1 flex items-start justify-between gap-3">
        <Skeleton className="skeleton--line" style={{ width: "6rem" }} />
        <span className="flex h-10 w-10 shrink-0 items-center justify-center">
          <Skeleton style={{ width: "1.75rem", height: "1.75rem" }} />
        </span>
      </div>
      <Skeleton style={{ width: "5rem", height: "2rem" }} />
      {hint ? <Skeleton className="mt-1" style={{ width: "8rem", height: "1.25rem" }} /> : null}
    </div>
  );
}

/** Card with the real title band text and a plot-sized block. */
export function SkeletonChartCard({ title, description, heightClassName = "h-64 sm:h-72", legend = false }: { title: ReactNode; description?: ReactNode; heightClassName?: string; legend?: boolean }) {
  return (
    <section className="card" aria-hidden="true">
      <h2 className="font-bold">{title}</h2>
      {description ? <p className="mb-4 mt-1 text-sm text-slate-500">{description}</p> : null}
      {legend ? <Skeleton className="mb-4 w-2/3" style={{ height: "1rem" }} /> : null}
      <Skeleton className={`w-full ${heightClassName}`} />
    </section>
  );
}

/** Rows of (label line, bar) like `Breakdown`, inside the same padded cell. */
export function SkeletonBreakdown({ title, rows = 5 }: { title: ReactNode; rows?: number }) {
  return (
    <section className="min-w-0 bg-[#F2F0EF] p-5" aria-hidden="true">
      <h3 className="mb-4 text-sm font-bold text-slate-800">{title}</h3>
      <div className="space-y-3">
        {Array.from({ length: rows }, (_, row) => (
          <div key={row}>
            <div className="mb-1 flex items-center justify-between gap-3">
              <Skeleton style={{ width: `${6 * ROW_WIDTHS[row % ROW_WIDTHS.length]}rem`, height: "1rem" }} />
              <Skeleton style={{ width: "2rem", height: "1rem" }} />
            </div>
            <Skeleton className="h-1.5 w-full" />
          </div>
        ))}
      </div>
    </section>
  );
}

/** Label line plus one `.input`-sized block per field. */
export function SkeletonForm({ labels }: { labels: ReactNode[] }) {
  return (
    <SkeletonRegion>
      <div className="grid gap-3 sm:grid-cols-2">
        {labels.map((label, index) => (
          <div key={index}>
            <span className="label">{label}</span>
            <Skeleton className="skeleton--input w-full" />
          </div>
        ))}
      </div>
    </SkeletonRegion>
  );
}

/** Stacked cards, for card lists. */
export function SkeletonCards({ count, heightClassName = "h-24" }: { count: number; heightClassName?: string }) {
  return (
    <SkeletonRegion>
      <div className="space-y-3">
        {Array.from({ length: count }, (_, index) => (
          <div key={index} className="card"><Skeleton className={`w-full ${heightClassName}`} /></div>
        ))}
      </div>
    </SkeletonRegion>
  );
}

/** Generic card body for pages without a specific skeleton: a title band, then rows of label and input bars. */
export function SkeletonPanel({ rows = 4 }: { rows?: number }) {
  return (
    <SkeletonRegion>
      <section className="card" aria-hidden="true">
        <Skeleton className="skeleton--line mb-4" style={{ width: "10rem" }} />
        <div className="space-y-4">
          {Array.from({ length: rows }, (_, index) => (
            <div key={index}>
              <Skeleton className="mb-1" style={{ width: `${5 + (index % 3)}rem`, height: "1rem" }} />
              <Skeleton className="skeleton--input w-full" />
            </div>
          ))}
        </div>
      </section>
    </SkeletonRegion>
  );
}
