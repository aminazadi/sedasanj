import { useEffect, useMemo, useState } from "react";
import { fmt, request } from "../api";
import { isOrgAdmin, useAuth } from "../auth";
import { ErrorBox, Loading, Pagination } from "../components/Widgets";
import type { OperatorScoreReport, ScoreCriterion, ScoreRubric } from "../types";

const emptyCriterion = (): ScoreCriterion => ({ title: "", description: "", weight: 0 });

export default function OperatorScores() {
  const limit = 25;
  const [offset, setOffset] = useState(0);
  const { session } = useAuth();
  const orgAdmin = isOrgAdmin(session?.role);
  const [days, setDays] = useState<number | null>(30);
  const [report, setReport] = useState<OperatorScoreReport | null>(null);
  const [rubric, setRubric] = useState<ScoreRubric | null>(null);
  const [criteria, setCriteria] = useState<ScoreCriterion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const totalWeight = useMemo(() => criteria.reduce((total, criterion) => total + (Number(criterion.weight) || 0), 0), [criteria]);
  useEffect(() => { const params=new URLSearchParams({offset:String(offset),limit:String(limit)});if(days)params.set("days",String(days));setReport(null);request<OperatorScoreReport>(`/v1/operator-scores?${params}`).then(setReport).catch((err) => setError(err.message)); }, [days, offset]);
  useEffect(() => { if (orgAdmin) request<ScoreRubric>("/v1/operator-score-rubric").then((data) => { setRubric(data); setCriteria(data.criteria); }).catch((err) => setError(err.message)); }, [orgAdmin]);
  function updateCriterion(index: number, patch: Partial<ScoreCriterion>) { setCriteria((current) => current.map((criterion, itemIndex) => itemIndex === index ? { ...criterion, ...patch } : criterion)); setSaved(null); }
  async function saveRubric() { setSaving(true); setError(null); setSaved(null); try { const data = await request<ScoreRubric>("/v1/operator-score-rubric", { method: "POST", body: JSON.stringify({ criteria }) }); setRubric(data); setCriteria(data.criteria); setSaved("معیارهای جدید برای ارزیابی تماس‌های بعدی ثبت شد."); } catch (err) { setError((err as Error).message); } finally { setSaving(false); } }
  if (error && !report) return <ErrorBox message={error} />;
  if (!report) return <Loading />;
  return <div className="space-y-5" dir="rtl">
    <div className="flex flex-wrap items-center justify-between gap-3"><h1 className="text-lg font-bold">امتیاز اپراتورها</h1><div className="flex gap-2">{[[7, "۷ روز"], [30, "۳۰ روز"], [90, "۹۰ روز"], [null, "همه"]].map(([value, label]) => <button key={String(label)} className={days === value ? "btn" : "btn-ghost"} onClick={() => {setDays(value as number | null);setOffset(0);}}>{label}</button>)}</div></div>
    {orgAdmin ? <section className="card space-y-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-bold text-slate-800">معیارهای امتیاز عملکرد</h2><p className="mt-1 text-xs text-slate-500">این نسخه برای تحلیل تماس‌های جدید استفاده می‌شود.</p></div>{rubric ? <span className="rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">نسخه {fmt.int(rubric.version)}</span> : null}</div><div className="space-y-3">{criteria.map((criterion, index) => <div key={index} className="grid gap-2 rounded-xl border border-slate-200 p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_7rem_auto]"><input className="input" value={criterion.title} onChange={(event) => updateCriterion(index, { title: event.target.value })} placeholder="عنوان معیار" aria-label="عنوان معیار" /><input className="input" value={criterion.description} onChange={(event) => updateCriterion(index, { description: event.target.value })} placeholder="توضیح معیار" aria-label="توضیح معیار" /><input className="input" type="number" min="1" max="100" value={criterion.weight || ""} onChange={(event) => updateCriterion(index, { weight: Number(event.target.value) })} placeholder="وزن" aria-label="وزن معیار" /><button className="btn-ghost text-rose-700 disabled:opacity-40" type="button" disabled={criteria.length <= 2} onClick={() => { setCriteria((current) => current.filter((_, itemIndex) => itemIndex !== index)); setSaved(null); }}>حذف</button></div>)}</div><div className="flex flex-wrap items-center justify-between gap-3"><button className="btn-ghost" type="button" disabled={criteria.length >= 8} onClick={() => { setCriteria((current) => [...current, emptyCriterion()]); setSaved(null); }}>افزودن معیار</button><div className="flex items-center gap-3"><span className={totalWeight === 100 ? "text-sm text-emerald-700" : "text-sm text-rose-700"}>جمع وزن‌ها: {fmt.int(totalWeight)} از ۱۰۰</span><button className="btn" type="button" disabled={saving || totalWeight !== 100 || criteria.some((criterion) => criterion.title.trim().length < 2 || criterion.description.trim().length < 2)} onClick={() => void saveRubric()}>{saving ? "در حال ثبت…" : "ثبت معیارها"}</button></div></div>{saved ? <p className="text-sm text-emerald-700">{saved}</p> : null}{error ? <ErrorBox message={error} /> : null}</section> : null}
    <div className="card overflow-x-auto"><table className="table min-w-[560px]"><thead><tr><th>رتبه</th><th>اپراتور</th><th>میانگین</th><th>تماس امتیازدار</th></tr></thead><tbody>{report.items.map((item) => <tr key={`${item.operator_id}-${item.operator_label}`}><td>{item.rank ? fmt.int(item.rank) : "—"}</td><td>{item.operator_label}</td><td>{item.average_score == null ? "—" : fmt.decimal(item.average_score)}</td><td>{fmt.int(item.scored_calls)}</td></tr>)}{report.items.length === 0 ? <tr><td colSpan={4}>امتیاز قابل نمایش وجود ندارد.</td></tr> : null}</tbody></table><Pagination page={Math.floor(offset/limit)+1} hasPrevious={offset>0} hasNext={offset+limit<report.total} total={report.total} onPrevious={()=>setOffset(Math.max(0,offset-limit))} onNext={()=>setOffset(offset+limit)}/></div>
  </div>;
}
