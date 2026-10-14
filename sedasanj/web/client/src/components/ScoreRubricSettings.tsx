import { useEffect, useMemo, useState } from "react";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "./Widgets";
import type { ScoreCriterion, ScoreRubric } from "../types";

const emptyCriterion = (): ScoreCriterion => ({ title: "", description: "", weight: 0 });

export default function ScoreRubricSettings() {
  const [rubric, setRubric] = useState<ScoreRubric | null>(null);
  const [criteria, setCriteria] = useState<ScoreCriterion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const totalWeight = useMemo(() => criteria.reduce((total, item) => total + (Number(item.weight) || 0), 0), [criteria]);

  useEffect(() => {
    request<ScoreRubric>("/v1/operator-score-rubric")
      .then((value) => { setRubric(value); setCriteria(value.criteria); })
      .catch((reason) => setError((reason as Error).message));
  }, []);

  function updateCriterion(index: number, patch: Partial<ScoreCriterion>) {
    setCriteria((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item));
    setSaved(false);
  }

  async function save() {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const value = await request<ScoreRubric>("/v1/operator-score-rubric", { method: "POST", body: { criteria } });
      setRubric(value);
      setCriteria(value.criteria);
      setSaved(true);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!rubric) return error ? <ErrorBox message={error} /> : <Loading />;
  return <section className="card space-y-5" dir="rtl">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="font-bold text-slate-800">معیارهای امتیاز عملکرد اپراتورها</h2><p className="mt-1 text-sm text-slate-500">نسخه جدید برای ارزیابی تماس‌های بعدی به کار می‌رود.</p></div>
      <span className="rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700">نسخه {fmt.int(rubric.version)}</span>
    </header>
    <div className="space-y-3">{criteria.map((item, index) => <div key={index} className="grid gap-2 rounded-xl border border-slate-200 p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_7rem_auto]">
      <input className="input" value={item.title} onChange={(event) => updateCriterion(index, { title: event.target.value })} placeholder="عنوان معیار" aria-label="عنوان معیار" />
      <input className="input" value={item.description} onChange={(event) => updateCriterion(index, { description: event.target.value })} placeholder="توضیح معیار" aria-label="توضیح معیار" />
      <input className="input" type="number" min="1" max="100" value={item.weight || ""} onChange={(event) => updateCriterion(index, { weight: Number(event.target.value) })} placeholder="وزن" aria-label="وزن معیار" />
      <button className="btn-ghost text-rose-700 disabled:opacity-40" type="button" disabled={criteria.length <= 2} onClick={() => { setCriteria((current) => current.filter((_, itemIndex) => itemIndex !== index)); setSaved(false); }}>حذف</button>
    </div>)}</div>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <button className="btn-ghost" type="button" disabled={criteria.length >= 8} onClick={() => { setCriteria((current) => [...current, emptyCriterion()]); setSaved(false); }}>افزودن معیار</button>
      <div className="flex flex-wrap items-center gap-3"><span className={totalWeight === 100 ? "text-sm text-emerald-700" : "text-sm text-rose-700"}>جمع وزن‌ها: {fmt.int(totalWeight)} از {fmt.int(100)}</span><button className="btn" type="button" disabled={saving || totalWeight !== 100 || criteria.some((item) => item.title.trim().length < 2 || item.description.trim().length < 2)} onClick={() => void save()}>{saving ? "در حال ثبت…" : "ثبت معیارها"}</button></div>
    </div>
    {saved ? <p className="text-sm text-emerald-700">معیارهای جدید ثبت شد.</p> : null}
    <ErrorBox message={error} />
  </section>;
}
