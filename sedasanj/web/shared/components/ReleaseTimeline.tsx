import { useMemo, useState } from "react";

export type ReleaseSeverity = "normal" | "recommended" | "critical" | "security";

export interface ReleaseEntry {
  id: string;
  version: string;
  title: string;
  severity: ReleaseSeverity;
  html: string;
  published_at: string | null;
}

export const SEVERITY_META: Record<ReleaseSeverity, { label: string; badge: string; dot: string }> = {
  normal: { label: "عادی", badge: "bg-slate-100 text-slate-700", dot: "bg-slate-400" },
  recommended: { label: "توصیه‌شده", badge: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  critical: { label: "مهم", badge: "bg-amber-50 text-amber-800", dot: "bg-amber-500" },
  // The theme maps rose/red to neutral, so security leans on the accent colour with a ring.
  security: { label: "امنیتی", badge: "bg-amber-100 text-amber-900 ring-1 ring-amber-500", dot: "bg-amber-700" },
};

/** Typography for the TinyMCE output; Tailwind preflight strips list and heading styles. */
export const RELEASE_NOTES_CLASS =
  "text-sm leading-7 text-slate-700 [&_a]:text-emerald-700 [&_a]:underline [&_blockquote]:border-r-4 " +
  "[&_blockquote]:border-slate-300 [&_blockquote]:pr-3 [&_blockquote]:text-slate-500 [&_code]:rounded " +
  "[&_code]:bg-slate-100 [&_code]:px-1 [&_code]:font-mono [&_code]:text-[0.85em] [&_h2]:mb-1 [&_h2]:mt-4 " +
  "[&_h2]:text-base [&_h2]:font-bold [&_h3]:mb-1 [&_h3]:mt-3 [&_h3]:font-bold [&_h4]:font-semibold " +
  "[&_hr]:my-3 [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pr-6 [&_p]:my-1.5 [&_pre]:my-2 [&_pre]:overflow-x-auto " +
  "[&_pre]:rounded-lg [&_pre]:bg-slate-900 [&_pre]:p-3 [&_pre]:text-left [&_pre]:text-slate-100 " +
  "[&_pre]:[direction:ltr] [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:my-2 [&_table]:w-full " +
  "[&_td]:border [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-slate-200 " +
  "[&_th]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_ul]:list-disc [&_ul]:pr-6";

const digits = (value: string) => value.replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);

function formatDate(iso: string | null): string {
  if (!iso) return "منتشرنشده";
  return new Date(iso).toLocaleDateString("fa-IR-u-ca-persian", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "Asia/Tehran",
  });
}

export function SeverityBadge({ severity }: { severity: ReleaseSeverity }) {
  const meta = SEVERITY_META[severity] ?? SEVERITY_META.normal;
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${meta.badge}`}>{meta.label}</span>;
}

export function ReleaseNotes({ html, sanitize }: { html: string; sanitize: (html: string) => string }) {
  return <div className={RELEASE_NOTES_CLASS} dangerouslySetInnerHTML={{ __html: sanitize(html) }} />;
}

export default function ReleaseTimeline({
  entries,
  sanitize,
  currentVersion,
  showFilters = true,
}: {
  entries: ReleaseEntry[];
  sanitize: (html: string) => string;
  currentVersion?: string | null;
  showFilters?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState<ReleaseSeverity | "">("");

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entries.filter((entry) => {
      if (severity && entry.severity !== severity) return false;
      if (!needle) return true;
      return `${entry.version} ${entry.title} ${entry.html.replace(/<[^>]+>/g, " ")}`.toLowerCase().includes(needle);
    });
  }, [entries, query, severity]);

  return (
    <div className="space-y-4">
      {showFilters ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-600 sm:max-w-xs"
            placeholder="جستجو در تغییرات…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-600"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as ReleaseSeverity | "")}
          >
            <option value="">همهٔ اهمیت‌ها</option>
            {(Object.keys(SEVERITY_META) as ReleaseSeverity[]).map((key) => (
              <option key={key} value={key}>
                {SEVERITY_META[key].label}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {visible.length === 0 ? (
        <div className="py-10 text-center text-slate-400">نسخه‌ای یافت نشد.</div>
      ) : (
        <ol className="relative border-r-2 border-slate-200 pr-6">
          {visible.map((entry) => {
            const meta = SEVERITY_META[entry.severity] ?? SEVERITY_META.normal;
            const isCurrent = currentVersion === entry.version;
            return (
              <li key={entry.id} id={`v${entry.version}`} className="relative mb-8 last:mb-0">
                <span
                  className={`absolute -right-[33px] top-1.5 h-4 w-4 rounded-full ring-4 ring-white ${meta.dot}`}
                  aria-hidden="true"
                />
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <a href={`#v${entry.version}`} className="font-mono text-lg font-extrabold text-slate-900" dir="ltr" data-keep-latin-digits>
                    v{entry.version}
                  </a>
                  <SeverityBadge severity={entry.severity} />
                  {isCurrent ? (
                    <span className="rounded-full bg-sky-50 px-2 py-0.5 text-xs font-medium text-sky-700">نسخهٔ فعلی شما</span>
                  ) : null}
                  <span className="text-xs text-slate-500">{digits(formatDate(entry.published_at))}</span>
                </div>
                <h3 className="mb-2 font-bold text-slate-800">{entry.title}</h3>
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <ReleaseNotes html={entry.html} sanitize={sanitize} />
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
