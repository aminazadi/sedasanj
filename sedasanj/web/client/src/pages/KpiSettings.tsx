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
  ["trend", "روند عملکرد"],
  ["funnel", "قیف فروش"],
  ["sentiment", "احساس مشتری"],
  ["operator_comparison", "مقایسه اپراتورها"],
  ["talk_balance", "تعادل گفت‌وگو"],
  ["tasks", "وضعیت کارها"],
  ["coaching", "بازخورد عملکرد"],
  ["actions", "اقدام‌های ضروری"],
] as const;

interface Settings { follow_up_sla_hours: number; minimum_sample_size: number; probable_confidence_threshold: number; hot_opportunity_threshold: number; operator_team_comparison_visible: boolean; dashboard_widgets: string[]; taxonomy_version: number; funnel_stages: string[]; objection_taxonomy: string[] }
interface Team { id: string; name: string; active: boolean; members: Array<{ id: string; name: string; valid_from: string }> }
const METRIC_LABELS: Record<string, string> = { conversion_rate: "نرخ تبدیل", quality_score: "امتیاز کیفیت", follow_up_sla_rate: "پیگیری در SLA" };

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
  async function load() {
    try {
      const [config, teamRows, userRows, goalRows] = await Promise.all([request<{ version: number; settings: Settings }>("/v1/kpi/settings"), request<Team[]>("/v1/kpi/teams"), request<Page<User>>("/v1/auth/users?limit=100"), request<Page<Goal>>(`/v1/kpi/goals?limit=${limit}&offset=${goalOffset}`)]);
      setVersion(config.version); setSettings(config.settings); setTeams(teamRows); setUsers(userRows.items.filter((item) => item.role === "operator")); setGoals(goalRows.items); setGoalTotal(goalRows.total);
    } catch (reason) { setError((reason as Error).message); }
  }
  useEffect(() => { void load(); }, [goalOffset]);
  async function save() { if (!settings) return; try { const row = await request<{ version: number; settings: Settings }>("/v1/kpi/settings", { method: "PUT", body: settings }); setVersion(row.version); setSettings(row.settings); setSaved("تنظیمات KPI ثبت شد."); } catch (reason) { setError((reason as Error).message); } }
  function openDialog(kind: "team" | "assign" | "goal") { setDialogError(null); setDialog(kind); }
  function closeDialog() { setDialog(null); setDialogError(null); }
  async function submitDialog(action: () => Promise<void>) { setDialogBusy(true); setDialogError(null); try { await action(); setDialog(null); } catch (reason) { setDialogError((reason as Error).message); } finally { setDialogBusy(false); } }
  async function createTeam() { await request("/v1/kpi/teams", { method: "POST", body: { name: teamName } }); setTeamName(""); await load(); }
  async function assign() { await request(`/v1/kpi/teams/${member.team_id}/members`, { method: "POST", body: { operator_id: member.operator_id, valid_from: new Date().toISOString() } }); await load(); }
  async function createGoal() { await request("/v1/kpi/goals", { method: "POST", body: { ...goal, target_value: Number(goal.target_value), team_id: goal.team_id || null, valid_from: new Date(goal.valid_from).toISOString(), valid_to: new Date(goal.valid_to).toISOString() } }); await load(); }
  if (!settings) return error ? <ErrorBox message={error} /> : <Loading />;
  return <div className="space-y-4">{embedded ? <p className="text-sm text-slate-500">تنظیمات KPI فروش · نسخه {fmt.int(version)} · تمام تغییرات نسخه‌دار و قابل ممیزی هستند.</p> : <PageHeader title="تنظیمات KPI فروش" description={`نسخه ${fmt.int(version)} · تمام تغییرات نسخه‌دار و قابل ممیزی هستند.`} />}{error ? <ErrorBox message={error} /> : null}
    <section className="card space-y-4"><h2 className="font-bold">آستانه‌ها و سیاست نمایش</h2><div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4"><label><span className="label">SLA پیگیری (ساعت)</span><input className="input" type="number" value={settings.follow_up_sla_hours} onChange={(e) => setSettings({ ...settings, follow_up_sla_hours: Number(e.target.value) })} /></label><label><span className="label">حداقل نمونه</span><input className="input" type="number" value={settings.minimum_sample_size} onChange={(e) => setSettings({ ...settings, minimum_sample_size: Number(e.target.value) })} /></label><label><span className="label">اطمینان فرصت محتمل</span><input className="input" type="number" step="0.05" min="0" max="1" value={settings.probable_confidence_threshold} onChange={(e) => setSettings({ ...settings, probable_confidence_threshold: Number(e.target.value) })} /></label><label><span className="label">آستانه فرصت داغ</span><input className="input" type="number" step="0.05" min="0" max="1" value={settings.hot_opportunity_threshold} onChange={(e) => setSettings({ ...settings, hot_opportunity_threshold: Number(e.target.value) })} /></label><label><span className="label">نسخه taxonomy</span><input className="input" type="number" min="1" value={settings.taxonomy_version} onChange={(e) => setSettings({ ...settings, taxonomy_version: Number(e.target.value) })} /></label><label className="md:col-span-2"><span className="label">مراحل قیف با ویرگول</span><input className="input" dir="ltr" value={settings.funnel_stages.join(",")} onChange={(e) => setSettings({ ...settings, funnel_stages: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label><label className="md:col-span-2"><span className="label">taxonomy اعتراض‌ها با ویرگول</span><input className="input" dir="ltr" value={settings.objection_taxonomy.join(",")} onChange={(e) => setSettings({ ...settings, objection_taxonomy: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label></div><ToggleSwitch checked={settings.operator_team_comparison_visible} onChange={(checked) => setSettings({ ...settings, operator_team_comparison_visible: checked })} label="نمایش هدف تیم به اپراتور" labelClassName="text-sm" /><div className="border-t border-[color:var(--line)] pt-4"><h3 className="font-bold">ویجت‌های داشبورد</h3><p className="field-hint">نمایش این بخش‌ها برای تمام اعضای سازمان کنترل می‌شود.</p><div className="mt-3 grid gap-3 sm:grid-cols-2">{DASHBOARD_WIDGETS.map(([key, label]) => <ToggleSwitch key={key} checked={settings.dashboard_widgets.includes(key)} onChange={(checked) => setSettings({ ...settings, dashboard_widgets: checked ? [...settings.dashboard_widgets, key] : settings.dashboard_widgets.filter((item) => item !== key) })} label={label} labelClassName="text-sm" />)}</div></div><div className="form-actions"><button className="btn" type="button" onClick={() => void save()}>ثبت نسخه جدید</button>{saved ? <span className="form-success" role="status">{saved}</span> : null}</div></section>
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
        <label><span>مقدار هدف</span><input className="input" type="number" value={goal.target_value} onChange={(e) => setGoal({ ...goal, target_value: Number(e.target.value) })} required /></label>
        <label className="sm:col-span-2"><span>دامنه</span><select className="input" value={goal.team_id} onChange={(e) => setGoal({ ...goal, team_id: e.target.value })}><option value="">کل سازمان</option>{teams.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <div className="demo-field"><span>تاریخ شروع</span><JalaliDatePicker value={goal.valid_from} onChange={(value) => setGoal({ ...goal, valid_from: value })} placeholder="تاریخ شروع" /></div>
        <div className="demo-field"><span>تاریخ پایان</span><JalaliDatePicker value={goal.valid_to} onChange={(value) => setGoal({ ...goal, valid_to: value })} placeholder="تاریخ پایان" /></div>
      </div>
    </FormDialog>
  </div>;
}
