import { hasPanelAccess, SETTINGS_ACCESS } from "../lib/panelAccess";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { isOrgAdmin, useAuth } from "../auth";
import AiInstructionsPanel from "../components/AiInstructionsPanel";
import JalaseNegarPairing from "../components/JalaseNegarPairing";
import ScoreRubricSettings from "../components/ScoreRubricSettings";
import Account from "./Account";
import OrganizationData from "./OrganizationData";
import KpiSettings from "./KpiSettings";
import { PageHeader } from "../components/PageHeader";

const TABS = [
  { id: "scoring", label: "امتیاز عملکرد", description: "معیارهای ارزیابی تماس" },
  { id: "ai", label: "دستورهای هوش مصنوعی", description: "صورت‌جلسه و مربی" },
  { id: "kpi", label: "KPI و تیم‌ها", description: "داشبورد، اهداف و اعضا" },
  { id: "users", label: "کاربران", description: "دسترسی اعضای سازمان" },
  { id: "integrations", label: "اتصال‌ها", description: "جلسه‌نگار، کلید API و وب‌هوک" },
  { id: "data", label: "داده‌ها", description: "بک‌آپ، بازیابی و خروجی" },
] as const;

export default function AccountSettings() {
  const { session } = useAuth();
  const orgAdmin = isOrgAdmin(session?.role);
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab");
  const tabs = (orgAdmin ? TABS : TABS.filter((item) => item.id === "integrations")).filter(item => hasPanelAccess(session, SETTINGS_ACCESS[item.id]));
  const tab = tabs.find((item) => item.id === requested)?.id ?? tabs[0]?.id;

  if (!tab) return <p role="alert">دسترسی تنظیمات فعال نیست؛ از مدیر سازمان بخواهید بررسی کند.</p>;

  if (requested && requested !== tab) {
    const next = new URLSearchParams(searchParams);
    next.set("tab", tab);
    return <Navigate to={{ search: `?${next}` }} replace />;
  }

  function selectTab(nextTab: string) {
    const next = new URLSearchParams(searchParams);
    next.set("tab", nextTab);
    setSearchParams(next);
  }

  return <div className="space-y-4">
    <PageHeader title="تنظیمات حساب" description={orgAdmin ? "مدیریت معیارهای ارزیابی، KPI و تنظیمات سازمان" : "مدیریت اتصال‌های حساب کاربری"} actions={orgAdmin && hasPanelAccess(session, "reports") ? <Link className="btn-ghost" to="/scheduled-reports?tab=settings">تنظیم گزارش‌های زمان‌بندی‌شده</Link> : undefined} />
    <nav className="panel-tabs sm:grid-cols-2 xl:grid-cols-6" aria-label="بخش‌های تنظیمات حساب">
      {tabs.map((item) => <button key={item.id} type="button" aria-current={tab === item.id ? "page" : undefined} onClick={() => selectTab(item.id)} className="panel-tab">
        <span className="block font-bold">{item.label}</span><span className="mt-1 block text-xs opacity-75">{orgAdmin ? item.description : "اپ جلسه‌نگار و دستگاه‌ها"}</span>
      </button>)}
    </nav>
    {tab === "scoring" ? <ScoreRubricSettings /> : null}
    {tab === "ai" ? <AiInstructionsPanel /> : null}
    {tab === "kpi" ? <KpiSettings embedded /> : null}
    {tab === "integrations" ? <JalaseNegarPairing /> : null}
    {orgAdmin && (tab === "users" || tab === "integrations") ? <Account key={tab} section={tab} /> : null}
    {tab === "data" ? <OrganizationData /> : null}
  </div>;
}
