import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { OperatorScoreReport } from "../types";
import { useSearchParams } from "react-router-dom";
import { DateRangePicker } from "../components/DateRangePicker";
import { PageHeader } from "../components/PageHeader";

export default function OperatorScores() {
  const limit = 25;
  const [searchParams, setSearchParams] = useSearchParams();
  const offset = Math.max(0, Number(searchParams.get("offset")) || 0);
  const range = searchParams.get("range") ?? "30";
  const from = searchParams.get("from") ?? "";
  const to = searchParams.get("to") ?? "";
  const [report, setReport] = useState<OperatorScoreReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (range === "custom" && (!from || !to)) return; const params=new URLSearchParams({offset:String(offset),limit:String(limit)});if (range === "custom") { params.set("from", new Date(`${from}T00:00:00`).toISOString()); params.set("to", new Date(`${to}T23:59:59.999`).toISOString()); } else { params.set("days", range); } setReport(null);setError(null);request<OperatorScoreReport>(`/v1/operator-scores?${params}`).then(setReport).catch((err) => setError(err.message)); }, [from, offset, range, to]);
  function updateRange(nextRange: { range: string; from?: string; to?: string }) {
    const next = new URLSearchParams(searchParams);
    next.set("range", nextRange.range);
    if (nextRange.range === "custom") { if (nextRange.from) next.set("from", nextRange.from); if (nextRange.to) next.set("to", nextRange.to); } else { next.delete("from"); next.delete("to"); }
    next.delete("offset");
    setSearchParams(next);
  }
  function updateOffset(nextOffset: number) { const next = new URLSearchParams(searchParams); if (nextOffset) next.set("offset", String(nextOffset)); else next.delete("offset"); setSearchParams(next); }
  if (error && !report) return <ErrorBox message={error} />;
  if (range === "custom" && (!from || !to)) return <div className="space-y-5" dir="rtl"><PageHeader title="امتیاز اپراتورها" description="مقایسه عملکرد اپراتورها در بازه انتخابی" actions={<DateRangePicker range={range} from={from} to={to} onChange={updateRange} compact />} /></div>;
  if (!report) return <Loading />;
  return <div className="space-y-5" dir="rtl">
    <PageHeader title="امتیاز اپراتورها" description="مقایسه عملکرد اپراتورها در بازه انتخابی" actions={<DateRangePicker range={range} from={from} to={to} onChange={updateRange} compact />} />
    <section className="card overflow-x-auto">{report.items.length ? <><table className="table min-w-[560px]"><thead><tr><th>رتبه</th><th>اپراتور</th><th>میانگین</th><th>تماس امتیازدار</th></tr></thead><tbody>{report.items.map((item) => <tr key={`${item.operator_id}-${item.operator_label}`}><td>{item.rank ? fmt.int(item.rank) : "—"}</td><td>{item.operator_label}</td><td>{item.average_score == null ? "—" : fmt.decimal(item.average_score)}</td><td>{fmt.int(item.scored_calls)}</td></tr>)}</tbody></table><Pagination page={Math.floor(offset/limit)+1} hasPrevious={offset>0} hasNext={offset+limit<report.total} total={report.total} onPrevious={()=>updateOffset(Math.max(0,offset-limit))} onNext={()=>updateOffset(offset+limit)}/></> : <Empty />}</section>
  </div>;
}
