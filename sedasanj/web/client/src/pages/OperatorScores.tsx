import { useEffect, useState } from "react";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { OperatorScoreReport } from "../types";
import TableFilters from "@cbi/web-shared/components/TableFilters";
import { useSearchParams } from "react-router-dom";

export default function OperatorScores() {
  const limit = 25;
  const [searchParams, setSearchParams] = useSearchParams();
  const offset = Math.max(0, Number(searchParams.get("offset")) || 0);
  const days = searchParams.get("days") === "all" ? null : Number(searchParams.get("days")) || 30;
  const [report, setReport] = useState<OperatorScoreReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { const params=new URLSearchParams({offset:String(offset),limit:String(limit)});if(days)params.set("days",String(days));setReport(null);setError(null);request<OperatorScoreReport>(`/v1/operator-scores?${params}`).then(setReport).catch((err) => setError(err.message)); }, [days, offset]);
  function updateFilters(nextDays: number | null, nextOffset = 0) {
    const next = new URLSearchParams(searchParams);
    next.set("days", nextDays === null ? "all" : String(nextDays));
    if (nextOffset) next.set("offset", String(nextOffset)); else next.delete("offset");
    setSearchParams(next);
  }
  if (error && !report) return <ErrorBox message={error} />;
  if (!report) return <Loading />;
  return <div className="space-y-5" dir="rtl">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-xl font-black">امتیاز اپراتورها</h1><p className="mt-1 text-sm text-slate-500">مقایسه عملکرد اپراتورها در بازه انتخابی</p></div><TableFilters><div className="flex flex-wrap gap-2">{[[7, "۷ روز"], [30, "۳۰ روز"], [90, "۹۰ روز"], [null, "همه"]].map(([value, label]) => <button key={String(label)} className={days === value ? "btn" : "btn-ghost"} onClick={() => updateFilters(value as number | null)}>{label}</button>)}</div></TableFilters></header>
    <section className="card overflow-x-auto">{report.items.length ? <><table className="table min-w-[560px]"><thead><tr><th>رتبه</th><th>اپراتور</th><th>میانگین</th><th>تماس امتیازدار</th></tr></thead><tbody>{report.items.map((item) => <tr key={`${item.operator_id}-${item.operator_label}`}><td>{item.rank ? fmt.int(item.rank) : "—"}</td><td>{item.operator_label}</td><td>{item.average_score == null ? "—" : fmt.decimal(item.average_score)}</td><td>{fmt.int(item.scored_calls)}</td></tr>)}</tbody></table><Pagination page={Math.floor(offset/limit)+1} hasPrevious={offset>0} hasNext={offset+limit<report.total} total={report.total} onPrevious={()=>updateFilters(days,Math.max(0,offset-limit))} onNext={()=>updateFilters(days,offset+limit)}/></> : <Empty />}</section>
  </div>;
}
