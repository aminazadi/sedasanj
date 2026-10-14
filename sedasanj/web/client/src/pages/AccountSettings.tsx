import { useSearchParams } from "react-router-dom";
import ScoreRubricSettings from "../components/ScoreRubricSettings";
import Account, { type AccountSection } from "./Account";
import KpiSettings from "./KpiSettings";

const TABS = [
  { id: "scoring", label: "امتیاز عملکرد", description: "معیارهای ارزیابی تماس" },
  { id: "kpi", label: "KPI و تیم‌ها", description: "داشبورد، اهداف و اعضا" },
  { id: "users", label: "کاربران", description: "دسترسی اعضای سازمان" },
  { id: "integrations", label: "اتصال‌ها", description: "کلید API و وب‌هوک" },
  { id: "data", label: "داده‌ها", description: "خروجی و مدیریت داده" },
] as const;

export default function AccountSettings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab");
  const tab = TABS.find((item) => item.id === requested)?.id ?? "scoring";

  function selectTab(nextTab: string) {
    const next = new URLSearchParams(searchParams);
    next.set("tab", nextTab);
    setSearchParams(next);
  }

  return <div className="space-y-5" dir="rtl">
    <header><h1 className="text-2xl font-bold text-[#4B6E48]">تنظیمات حساب</h1><p className="mt-1 text-sm text-slate-500">مدیریت معیارهای ارزیابی، KPI و تنظیمات سازمان</p></header>
    <nav className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5" aria-label="بخش‌های تنظیمات حساب">
      {TABS.map((item) => <button key={item.id} type="button" aria-current={tab === item.id ? "page" : undefined} onClick={() => selectTab(item.id)} className={`min-h-20 rounded-xl border p-3 text-right transition-colors ${tab === item.id ? "border-[#4B6E48] bg-[#E7ECDD] text-[#345331]" : "border-slate-200 bg-white text-slate-700 hover:border-[#B2AC88]"}`}>
        <span className="block font-bold">{item.label}</span><span className="mt-1 block text-xs opacity-75">{item.description}</span>
      </button>)}
    </nav>
    {tab === "scoring" ? <ScoreRubricSettings /> : null}
    {tab === "kpi" ? <KpiSettings embedded /> : null}
    {tab === "users" || tab === "integrations" || tab === "data" ? <Account key={tab} section={tab as AccountSection} /> : null}
  </div>;
}
