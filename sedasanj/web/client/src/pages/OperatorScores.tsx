import { fmt, request } from "../api";
import { Empty, ErrorBox, Pagination } from "../components/Widgets";
import type { OperatorScoreReport } from "../types";
import { useSearchParams } from "react-router-dom";
import { DateRangePicker } from "../components/DateRangePicker";
import { PageHeader } from "../components/PageHeader";
import { SkeletonTable, type SkeletonColumn } from "@cbi/web-shared/components/Skeleton";
import { useResource } from "@cbi/web-shared/lib/useResource";

const LIMIT = 25;
const COLUMNS: SkeletonColumn[] = [
  { label: "رتبه", width: "1.5rem" },
  { label: "اپراتور", width: "8rem" },
  { label: "میانگین", width: "3rem" },
  { label: "تماس امتیازدار", width: "2.5rem" },
];

export default function OperatorScores() {
  const [searchParams, setSearchParams] = useSearchParams();
  const offset = Math.max(0, Number(searchParams.get("offset")) || 0);
  const range = searchParams.get("range") ?? "30";
  const from = searchParams.get("from") ?? "";
  const to = searchParams.get("to") ?? "";
  const incompleteRange = range === "custom" && (!from || !to);
  const scores = useResource<OperatorScoreReport | null>(async (signal) => {
    if (incompleteRange) return null;
    const params = new URLSearchParams({ offset: String(offset), limit: String(LIMIT) });
    if (range === "custom") {
      params.set("from", new Date(`${from}T00:00:00`).toISOString());
      params.set("to", new Date(`${to}T23:59:59.999`).toISOString());
    } else {
      params.set("days", range);
    }
    return request<OperatorScoreReport>(`/v1/operator-scores?${params}`, { signal });
  }, [from, offset, range, to]);
  const report = scores.data;

  function updateRange(nextRange: { range: string; from?: string; to?: string }) {
    const next = new URLSearchParams(searchParams);
    next.set("range", nextRange.range);
    if (nextRange.range === "custom") { if (nextRange.from) next.set("from", nextRange.from); if (nextRange.to) next.set("to", nextRange.to); } else { next.delete("from"); next.delete("to"); }
    next.delete("offset");
    setSearchParams(next);
  }
  function updateOffset(nextOffset: number) { const next = new URLSearchParams(searchParams); if (nextOffset) next.set("offset", String(nextOffset)); else next.delete("offset"); setSearchParams(next); }

  return <div className="space-y-5" dir="rtl">
    <PageHeader title="امتیاز اپراتورها" description="مقایسه عملکرد اپراتورها در بازه انتخابی" actions={<DateRangePicker range={range} from={from} to={to} onChange={updateRange} compact />} />
    <ErrorBox message={scores.error} />
    {incompleteRange ? null : <section className="card overflow-x-auto">
      {scores.loading ? <SkeletonTable columns={COLUMNS} rows={report?.items.length ? Math.min(report.items.length, LIMIT) : 8} className="min-w-[560px]" /> : report && report.items.length ? <table className="table min-w-[560px]"><thead><tr>{COLUMNS.map((column, index) => <th key={index}>{column.label}</th>)}</tr></thead><tbody>{report.items.map((item) => <tr key={`${item.operator_id}-${item.operator_label}`}><td>{item.rank ? fmt.int(item.rank) : "—"}</td><td>{item.operator_label}</td><td>{item.average_score == null ? "—" : fmt.decimal(item.average_score)}</td><td>{fmt.int(item.scored_calls)}</td></tr>)}</tbody></table> : <Empty />}
      {report ? <Pagination page={Math.floor(offset / LIMIT) + 1} hasPrevious={offset > 0} hasNext={offset + LIMIT < report.total} total={report.total} loading={scores.loading} onPrevious={() => updateOffset(Math.max(0, offset - LIMIT))} onNext={() => updateOffset(offset + LIMIT)} /> : null}
    </section>}
  </div>;
}
