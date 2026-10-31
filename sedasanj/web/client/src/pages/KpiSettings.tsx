import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import JalaliDatePicker from "@cbi/web-shared/components/JalaliDatePicker";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { fmt, request } from "../api";
import { Empty, ErrorBox, Loading, Pagination } from "../components/Widgets";
import FormDialog from "../components/FormDialog";
import SearchSelect from "../components/SearchSelect";
import teamArt from "../assets/team.webp";
import assignArt from "../assets/assign-operator.webp";
import goalArt from "../assets/goal.webp";
import { PageHeader } from "../components/PageHeader";
import type { Page, User } from "../types";

const DASHBOARD_WIDGETS = [
  ["trend", "روند عملکرد", "نمودار روزانهٔ تماس، فرصت، فروش و کیفیت."],
  ["funnel", "قیف فروش", "قیف «از تماس تا فروش» با نقطهٔ بیشترین ریزش."],
  ["sentiment", "احساس مشتری", "احساس مشتریان، اعتراض‌ها و موضوعات پرتکرار."],
  ["operator_comparison", "مقایسه اپراتورها", "مقایسهٔ اپراتورها برای مدیر؛ اپراتور آن را نمی‌بیند."],
  ["talk_balance", "تعادل گفت‌وگو", "سهم صحبت اپراتور و مشتری در «تحلیل‌های تکمیلی»."],
  ["tasks", "وضعیت کارها", "نرخ تکمیل و کارهای عقب‌افتاده در «تحلیل‌های تکمیلی»."],
  ["coaching", "بازخورد عملکرد", "نقاط قوت و اولویت‌های بهبود؛ اپراتور فقط دادهٔ خودش را می‌بیند."],
  ["actions", "اقدام‌های ضروری", "فرصت‌های داغ، کارهای عقب‌افتاده و هشدارها."],
] as const;

const FUNNEL_STAGES = [
  ["effective", "تماس مؤثر", true],
  ["qualified", "واجد شرایط", true],
  ["interested", "علاقه‌مند", false],
  ["follow_up", "پیگیری", false],
  ["proposal", "پیشنهاد", false],
  ["won", "فروش", true],
  ["lost", "باخت", true],
] as const;

interface Settings { follow_up_sla_hours: number; minimum_sample_size: number; probable_confidence_threshold: number; hot_opportunity_threshold: number; operator_team_comparison_visible: boolean; include_internal_calls: boolean; dashboard_widgets: string[]; taxonomy_version: number; funnel_stages: string[]; objection_taxonomy: string[] }
interface Team { id: string; name: string; active: boolean; members: Array<{ id: string; name: string; valid_from: string }> }
const METRIC_LABELS: Record<string, string> = { conversion_rate: "نرخ تبدیل (٪)", quality_score: "امتیاز کیفیت (از ۱۰۰)", follow_up_sla_rate: "پیگیری در SLA (٪)" };

interface Goal { id: string; team_id: string | null; metric: string; target_value: number; valid_from: string; valid_to: string }

export default function KpiSettings({ embedded = false }: { embedded?: boolean }) {
  const limit = 25;
  const [searchParams, setSearchParams] = useSearchParams();
  const goalOffset = Math.max(0, Number(searchParams.get("goal_offset")) || 0);
  function setGoalOffset(offset: number) {
    const next = new URLSearchParams(searchParams);
    if (offset) next.set("goal_offset", String(offset)); else next.delete("goal_offset");
    setSearchParams(next);
  }
  const [goalTotal, setGoalTotal] = useState(0);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [version, setVersion] = useState(0);
  const [teams, setTeams] = useState<Team[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [teamName, setTeamName] = useState("");
  const [member, setMember] = useState({ team_id: "", operator_id: "" });
  const [goal, setGoal] = useState({ metric: "conversion_rate", target_value: 20, team_id: "", valid_from: new Date().toISOString().slice(0, 10), valid_to: new Date(Date.now() + 365 * 86400000).toISOString().slice(0, 10) });
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"team" | "assign" | "goal" | null>(null);
  const [dialogBusy, setDialogBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [objectionText, setObjectionText] = useState("");
  async function load() {
    try {
      const [config, teamRows, userRows, goalRows] = await Promise.all([request<{ version: number; settings: Settings }>("/v1/kpi/settings"), request<Team[]>("/v1/kpi/teams"), request<Page<User>>("/v1/auth/users?limit=100"), request<Page<Goal>>(`/v1/kpi/goals?limit=${limit}&offset=${goalOffset}`)]);
      setVersion(config.version); setSettings(config.settings); setObjectionText(config.settings.objection_taxonomy.join(",")); setTeams(teamRows); setUsers(userRows.items.filter((item) => item.role === "operator")); setGoals(goalRows.items); setGoalTotal(goalRows.total);
    } catch (reason) { setError((reason as Error).message); }
  }
  useEffect(() => { void load(); }, [goalOffset]);
  function patch(change: Partial<Settings>) { setSaved(null); setError(null); setSettings((current) => (current ? { ...current, ...change } : current)); }
  function validate(value: Settings): string | null {
    if (!Number.isInteger(value.follow_up_sla_hours) || value.follow_up_sla_hours < 1 || value.follow_up_sla_hours > 720) return "SLA پیگیری باید عدد صحیح بین ۱ تا ۷۲۰ ساعت باشد.";
    if (!Number.isInteger(value.minimum_sample_size) || value.minimum_sample_size < 1 || value.minimum_sample_size > 1000) return "حداقل نمونه باید عدد صحیح بین ۱ تا ۱۰۰۰ باشد.";
    for (const threshold of [value.probable_confidence_threshold, value.hot_opportunity_threshold]) if (!(threshold >= 0 && threshold <= 1)) return "آستانه‌های اطمینان باید بین ۰ و ۱ باشند.";
    if (value.hot_opportunity_threshold < value.probable_confidence_threshold) return "آستانهٔ فرصت داغ نباید کمتر از اطمینان فرصت محتمل باشد.";
    if (!value.objection_taxonomy.length) return "حداقل یک اعتراض در taxonomy لازم است.";
    if (new Set(value.objection_taxonomy).size !== value.objection_taxonomy.length) return "مقدارهای taxonomy اعتراض‌ها باید یکتا باشند.";
    return null;
  }
  async function save() {
    if (!settings) return;
    const problem = validate(settings);
    if (problem) { setSaved(null); setError(problem); return; }
    try { const row = await request<{ version: number; settings: Settings }>("/v1/kpi/settings", { method: "PUT", body: settings }); setVersion(row.version); setSettings(row.settings); setObjectionText(row.settings.objection_taxonomy.join(",")); setError(null); setSaved("تنظیمات KPI ثبت شد."); } catch (reason) { setSaved(null); setError((reason as Error).message); }
  }
  function openDialog(kind: "team" | "assign" | "goal") { setDialogError(null); setDialog(kind); }
  function closeDialog() { setDialog(null); setDialogError(null); }
  async function submitDialog(action: () => Promise<void>) { setDialogBusy(true); setDialogError(null); try { await action(); setDialog(null); } catch (reason) { setDialogError((reason as Error).message); } finally { setDialogBusy(false); } }
  async function createTeam() { await request("/v1/kpi/teams", { method: "POST", body: { name: teamName } }); setTeamName(""); await load(); }
  async function assign() { await request(`/v1/kpi/teams/${member.team_id}/members`, { method: "POST", body: { operator_id: member.operator_id, valid_from: new Date().toISOString() } }); await load(); }
  async function createGoal() { await request("/v1/kpi/goals", { method: "POST", body: { ...goal, target_value: Number(goal.target_value), team_id: goal.team_id || null, valid_from: new Date(goal.valid_from).toISOString(), valid_to: new Date(goal.valid_to).toISOString() } }); await load(); }
  const versionText = version ? `نسخه ${fmt.int(version)}` : "هنوز نسخه‌ای ثبت نشده (مقادیر پیش‌فرض)";
  if (!settings) return error ? <ErrorBox message={error} /> : <Loading />;
  return <div className="space-y-4">{embedded ? <p className="text-sm text-slate-500">تنظیمات KPI فروش · {versionText} · تمام تغییرات نسخه‌دار و قابل ممیزی هستند.</p> : <PageHeader title="تنظیمات KPI فروش" description={`${versionText} · تمام تغییرات نسخه‌دار و قابل ممیزی هستند.`} />}{error ? <ErrorBox message={error} /> : null}
    <section className="card space-y-4"><h2 className="font-bold">آستانه‌ها و سیاست نمایش</h2>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <label><span className="label">SLA پیگیری (ساعت)</span><input className="input" type="number" min="1" max="720" value={settings.follow_up_sla_hours} onChange={(e) => patch({ follow_up_sla_hours: Number(e.target.value) })} /><span className="field-hint">مهلت انجام کار پیگیری؛ ۱ تا ۷۲۰ ساعت.</span></label>
        <label><span className="label">حداقل نمونه</span><input className="input" type="number" min="1" max="1000" value={settings.minimum_sample_size} onChange={(e) => patch({ minimum_sample_size: Number(e.target.value) })} /><span className="field-hint">اپراتور با تماس کمتر در جدول «نمونهٔ ناکافی» نشان داده می‌شود.</span></label>
        <label><span className="label">اطمینان فرصت محتمل</span><input className="input" type="number" step="0.05" min="0" max="1" value={settings.probable_confidence_threshold} onChange={(e) => patch({ probable_confidence_threshold: Number(e.target.value) })} /><span className="field-hint">حداقل اطمینان AI برای شمردن نتیجهٔ احتمالی؛ ۰ تا ۱.</span></label>
        <label><span className="label">آستانه فرصت داغ</span><input className="input" type="number" step="0.05" min="0" max="1" value={settings.hot_opportunity_threshold} onChange={(e) => patch({ hot_opportunity_threshold: Number(e.target.value) })} /><span className="field-hint">فرصت‌های بالاتر از این مقدار در «اقدام‌های ضروری» می‌آیند؛ نباید کمتر از اطمینان فرصت محتمل باشد.</span></label>
      </div>
      <div className="border-t border-[color:var(--line)] pt-4"><h3 className="font-bold">مراحل قیف فروش</h3><p className="field-hint">مراحل علامت‌خورده در قیف «مراحل فروش» و در تحلیل AI استفاده می‌شوند. چهار مرحلهٔ ضروری قابل حذف نیستند.</p><div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{FUNNEL_STAGES.map(([key, label, required]) => <ToggleSwitch key={key} checked={settings.funnel_stages.includes(key)} disabled={required} onChange={(checked) => patch({ funnel_stages: FUNNEL_STAGES.map(([stage]) => stage).filter((stage) => (stage === key ? checked : settings.funnel_stages.includes(stage))) })} label={label} labelClassName="text-sm" />)}</div></div>
      <label className="block"><span className="label">taxonomy اعتراض‌ها با ویرگول</span><input className="input" dir="ltr" value={objectionText} onChange={(e) => { setObjectionText(e.target.value); patch({ objection_taxonomy: e.target.value.split(",").map((item) => item.trim().toLowerCase()).filter(Boolean) }); }} /><span className="field-hint">مقدارهای انگلیسی و یکتا. اعتراض خارج از فهرست به <bdi dir="ltr">other</bdi> نگاشت می‌شود، پس آن را نگه دارید. نسخهٔ taxonomy فعلی {fmt.int(settings.taxonomy_version)} است و با تغییر مراحل یا اعتراض‌ها خودکار یکی بالا می‌رود؛ تماس‌های قبلی با نسخهٔ قدیمی نگه داشته می‌شوند.</span></label>
      <div><ToggleSwitch checked={settings.include_internal_calls} onChange={(checked) => patch({ include_internal_calls: checked })} label="تماس‌های داخلی را در KPI حساب کن" labelClassName="text-sm" /><p className="field-hint">به‌صورت پیش‌فرض خاموش است: تماس بین دو همکار در نرخ پاسخ، تبدیل، قیف، SLA و امتیاز اپراتور نمی‌آید.</p></div>
      <div><ToggleSwitch checked={settings.operator_team_comparison_visible} onChange={(checked) => patch({ operator_team_comparison_visible: checked })} label="نمایش هدف تیم به اپراتور" labelClassName="text-sm" /><p className="field-hint">اگر خاموش باشد، اپراتور در داشبورد خودش فقط هدف‌های سازمان را می‌بیند.</p></div>
      <div className="border-t border-[color:var(--line)] pt-4"><h3 className="font-bold">ویجت‌های داشبورد</h3><p className="field-hint">نمایش این بخش‌ها برای تمام اعضای سازمان کنترل می‌شود.</p><div className="mt-3 grid gap-3 sm:grid-cols-2">{DASHBOARD_WIDGETS.map(([key, label, hint]) => <div key={key}><ToggleSwitch checked={settings.dashboard_widgets.includes(key)} onChange={(checked) => patch({ dashboard_widgets: DASHBOARD_WIDGETS.map(([widget]) => widget).filter((widget) => (widget === key ? checked : settings.dashboard_widgets.includes(widget))) })} label={label} labelClassName="text-sm" /><p className="field-hint">{hint}</p></div>)}</div></div>
      <div className="form-actions"><button className="btn" type="button" onClick={() => void save()}>ثبت نسخه جدید</button>{saved ? <span className="form-success" role="status">{saved}</span> : null}</div></section>
    <section className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-bold">تیم‌ها و اعضا</h2><div className="flex flex-wrap gap-2"><button className="btn-ghost" type="button" onClick={() => openDialog("assign")} disabled={!teams.length}>تخصیص اپراتور</button><button className="btn" type="button" onClick={() => openDialog("team")}>ایجاد تیم</button></div></div>
      {teams.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{teams.map((item) => <div key={item.id} className="border border-[color:var(--line)] p-3"><strong>{item.name}</strong><p className="field-hint mt-2">{item.members.length ? item.members.map((memberRow) => memberRow.name).join("، ") : "بدون عضو"}</p></div>)}</div> : <Empty>هنوز تیمی ساخته نشده است.</Empty>}
    </section>
    <section className="card space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-bold">اهداف سازمان و تیم</h2><button className="btn" type="button" onClick={() => openDialog("goal")}>ثبت هدف</button></div>
      <div className="overflow-x-auto"><table className="table"><thead><tr><th>معیار</th><th>دامنه</th><th>هدف</th><th>شروع</th><th>پایان</th></tr></thead><tbody>{goals.map((item) => <tr key={item.id}><td>{METRIC_LABELS[item.metric] ?? item.metric}</td><td>{teams.find((team) => team.id === item.team_id)?.name ?? "سازمان"}</td><td>{fmt.decimal(item.target_value)}</td><td>{fmt.date(item.valid_from)}</td><td>{fmt.date(item.valid_to)}</td></tr>)}</tbody></table><Pagination page={Math.floor(goalOffset/limit)+1} hasPrevious={goalOffset>0} hasNext={goalOffset+limit<goalTotal} total={goalTotal} onPrevious={()=>setGoalOffset(Math.max(0,goalOffset-limit))} onNext={()=>setGoalOffset(goalOffset+limit)}/></div></section>
    <FormDialog open={dialog === "team"} title="ایجاد تیم جدید" description="تیم‌ها برای گروه‌بندی اپراتورها و تعریف هدف مشترک استفاده می‌شوند." art={teamArt} submitLabel="ایجاد تیم" busy={dialogBusy} error={dialogError} onClose={closeDialog} onSubmit={() => void submitDialog(createTeam)}>
      <label><span>نام تیم</span><input className="input" value={teamName} onChange={(e) => setTeamName(e.target.value)} required minLength={2} autoFocus /></label>
    </FormDialog>
    <FormDialog open={dialog === "assign"} title="تخصیص اپراتور به تیم" description="عضویت از لحظهٔ ثبت شروع می‌شود و در گزارش‌ها زمان‌دار نگه داشته می‌شود." art={assignArt} submitLabel="تخصیص" busy={dialogBusy} error={dialogError} onClose={closeDialog} onSubmit={() => void submitDialog(assign)}>
      <label><span>تیم</span><select className="input" value={member.team_id} onChange={(e) => setMember({ ...member, team_id: e.target.value })} required><option value="">انتخاب تیم</option>{teams.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label><span>اپراتور</span><SearchSelect ariaLabel="اپراتور" emptyLabel="انتخاب اپراتور" searchPlaceholder="جستجوی اپراتور…" options={users.map((item) => ({ value: item.id, label: item.display_name ?? item.email, keywords: item.email }))} value={member.operator_id} onChange={(value) => setMember({ ...member, operator_id: value })} /></label>
    </FormDialog>
    <FormDialog open={dialog === "goal"} title="ثبت هدف جدید" description="هدف برای کل سازمان یا یک تیم در بازهٔ زمانی مشخص تعریف می‌شود." art={goalArt} submitLabel="ثبت هدف" busy={dialogBusy} error={dialogError} onClose={closeDialog} onSubmit={() => void submitDialog(createGoal)}>
      <div className="grid gap-[18px] sm:grid-cols-2">
        <label><span>معیار</span><select className="input" value={goal.metric} onChange={(e) => setGoal({ ...goal, metric: e.target.value })}>{Object.entries(METRIC_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        <label><span>مقدار هدف</span><input className="input" type="number" min="1" max="100" step="any" value={goal.target_value} onChange={(e) => setGoal({ ...goal, target_value: Number(e.target.value) })} required /></label>
        <label className="sm:col-span-2"><span>دامنه</span><select className="input" value={goal.team_id} onChange={(e) => setGoal({ ...goal, team_id: e.target.value })}><option value="">کل سازمان</option>{teams.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <div className="demo-field"><span>تاریخ شروع</span><JalaliDatePicker value={goal.valid_from} onChange={(value) => setGoal({ ...goal, valid_from: value })} placeholder="تاریخ شروع" /></div>
        <div className="demo-field"><span>تاریخ پایان</span><JalaliDatePicker value={goal.valid_to} onChange={(value) => setGoal({ ...goal, valid_to: value })} placeholder="تاریخ پایان" /></div>
      </div>
    </FormDialog>
  </div>;
}
