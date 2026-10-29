import { useEffect, useMemo, useState } from "react";
import { Icon } from "@iconify/react";
import trashIcon from "@iconify-icons/lucide/trash-2";
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
  return <section className="card space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="font-bold">معیارهای امتیاز عملکرد اپراتورها</h2><p className="section-hint">نسخه جدید برای ارزیابی تماس‌های بعدی به کار می‌رود.</p></div>
      <span className="badge badge-success">نسخه {fmt.int(rubric.version)}</span>
    </div>
    <div className="space-y-3">{criteria.map((item, index) => <div key={index} className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_7rem_auto]">
      <input className="input" value={item.title} onChange={(event) => updateCriterion(index, { title: event.target.value })} placeholder="عنوان معیار" aria-label="عنوان معیار" />
      <input className="input" value={item.description} onChange={(event) => updateCriterion(index, { description: event.target.value })} placeholder="توضیح معیار" aria-label="توضیح معیار" />
      <input className="input" type="number" min="1" max="100" value={item.weight || ""} onChange={(event) => updateCriterion(index, { weight: Number(event.target.value) })} placeholder="وزن" aria-label="وزن معیار" />
      <button className="btn-danger" type="button" disabled={criteria.length <= 2} onClick={() => { setCriteria((current) => current.filter((_, itemIndex) => itemIndex !== index)); setSaved(false); }} aria-label="حذف معیار" title="حذف معیار"><Icon icon={trashIcon} className="h-5 w-5" aria-hidden="true" /></button>
    </div>)}</div>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <button className="btn-ghost" type="button" disabled={criteria.length >= 8} onClick={() => { setCriteria((current) => [...current, emptyCriterion()]); setSaved(false); }}>افزودن معیار</button>
      <div className="flex flex-wrap items-center gap-3"><span className={totalWeight === 100 ? "text-sm text-brand-600" : "text-sm text-rose-700"}>جمع وزن‌ها: {fmt.int(totalWeight)} از {fmt.int(100)}</span><button className="btn" type="button" disabled={saving || totalWeight !== 100 || criteria.some((item) => item.title.trim().length < 2 || item.description.trim().length < 2)} onClick={() => void save()}>{saving ? "در حال ثبت…" : "ثبت معیارها"}</button></div>
    </div>
    {saved ? <p className="form-success" role="status">معیارهای جدید ثبت شد.</p> : null}
    <ErrorBox message={error} />
  </section>;
}
