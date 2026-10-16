import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import logo from "../assets/sedasanj-refined-master.svg";
import heroBackdrop from "../assets/manager-office-line-art.png";
import "./Landing.css";
import { fmt, request } from "../api";
import type { PublicPlan } from "../types";

type IconName = "arrow" | "brain" | "chart" | "check" | "chevron" | "clock" | "headset" | "layers" | "lock" | "menu" | "message" | "phone" | "pulse" | "quote" | "shield" | "spark" | "target" | "tasks" | "trend" | "users" | "x";

const paths: Record<IconName, ReactNode> = {
  arrow: <><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></>,
  brain: <><path d="M9.5 4A2.5 2.5 0 0 0 7 6.5v.2A3.5 3.5 0 0 0 5.5 13v.5A3.5 3.5 0 0 0 9 17h1V5.5A1.5 1.5 0 0 0 8.5 4Z"/><path d="M14.5 4A2.5 2.5 0 0 1 17 6.5v.2a3.5 3.5 0 0 1 1.5 6.3v.5A3.5 3.5 0 0 1 15 17h-1V5.5A1.5 1.5 0 0 1 15.5 4Z"/><path d="M7 9.5h3M14 9.5h3M7.5 14H10M14 14h2.5M10 20v-3M14 20v-3"/></>,
  chart: <><path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 3-4 3 2 5-7"/><path d="M16 6h2v2"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  chevron: <path d="m15 18-6-6 6-6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  headset: <><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><path d="M18 19c0 1.1-.9 2-2 2h-3"/><rect x="3" y="13" width="4" height="6" rx="2"/><rect x="17" y="13" width="4" height="6" rx="2"/></>,
  layers: <><path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></>,
  lock: <><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16"/></>,
  message: <><path d="M21 12a8 8 0 0 1-8 8H6l-3 2 1-5a9 9 0 1 1 17-5Z"/><path d="M8 12h.01M12 12h.01M16 12h.01"/></>,
  phone: <path d="M6.6 2.8 9 8l-2.1 1.8a15.8 15.8 0 0 0 7.3 7.3L16 15l5.2 2.4c.5.2.8.8.6 1.3l-.8 2.2c-.2.7-.9 1.1-1.6 1.1A17.4 17.4 0 0 1 2 4.6c0-.7.4-1.4 1.1-1.6l2.2-.8c.5-.2 1.1.1 1.3.6Z"/>,
  pulse: <path d="M3 12h4l2-7 4 14 2-7h6"/>,
  quote: <><path d="M9 11H5a4 4 0 0 0 4 4V8a4 4 0 0 0-4 4"/><path d="M19 11h-4a4 4 0 0 0 4 4V8a4 4 0 0 0-4 4"/></>,
  shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></>,
  spark: <><path d="m12 3 1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2L12 3Z"/><path d="m18 14 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14ZM5 13l.7 1.8 1.8.7-1.8.7L5 18l-.7-1.8-1.8-.7 1.8-.7L5 13Z"/></>,
  target: <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></>,
  tasks: <><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 3.5h6M8.5 9l1.5 1.5L13 7.5M8.5 15l1.5 1.5 3-3M15 9h1M15 15h1"/></>,
  trend: <><path d="m3 17 6-6 4 4 7-8"/><path d="M15 7h5v5"/></>,
  users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/></>,
  x: <><path d="m6 6 12 12M18 6 6 18"/></>,
};

function Icon({ name, size = 24 }: { name: IconName; size?: number }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

const benefits: Array<{ icon: IconName; title: string; body: string }> = [
  { icon: "chart", title: "داشبورد و گزارش‌های مدیریتی", body: "حجم تماس‌ها، روند کیفیت پاسخ‌گویی و وضعیت عملکرد تیم را در یک نگاه بررسی کنید و گزارش‌ها را بر اساس بازه زمانی و اپراتور فیلتر کنید." },
  { icon: "target", title: "ارزیابی کیفیت و عملکرد اپراتورها", body: "مکالمات را با معیارهای ارزیابی سازمان امتیازدهی کنید؛ عملکرد اپراتورها را مقایسه کنید و نقاط قوت و نیازهای آموزشی تیم را بشناسید." },
  { icon: "message", title: "متن و خلاصه قابل جست‌وجوی تماس‌ها", body: "به متن فارسی، خلاصه و نکات کلیدی مکالمات دسترسی داشته باشید؛ بدون شنیدن تمام فایل صوتی، جزئیات موردنیاز برای بررسی هر تماس را پیدا کنید." },
  { icon: "pulse", title: "تحلیل موضوع، احساس و نتیجه تماس", body: "موضوعات پرتکرار، لحن مشتری و نتیجه مکالمات را بررسی کنید تا دلایل نارضایتی و تماس‌های نیازمند توجه مدیر را شناسایی کنید." },
  { icon: "tasks", title: "مدیریت پیگیری‌ها و تعهدات", body: "اقدام‌های بعدی استخراج‌شده از مکالمات را همراه با وضعیت و سررسید مدیریت کنید و برای بررسی جزئیات، مستقیماً به تماس مرتبط برگردید." },
  { icon: "headset", title: "دستیار هوشمند سازمان", body: "درباره تماس‌ها، تحلیل‌ها و عملکرد اپراتورها سؤال بپرسید و پاسخ مستند به داده‌های سازمان را همراه با ارجاع به مکالمات مرتبط دریافت کنید." },
];
const steps = [
  { icon: "phone" as const, title: "دریافت امن تماس", body: "تماس‌های مرکز تلفن به‌صورت خودکار و همراه با اطلاعات لازم وارد جریان تحلیل می‌شوند." },
  { icon: "message" as const, title: "تبدیل گفتار به متن", body: "گفت‌وگوی مشتری و اپراتور تفکیک می‌شود تا محتوای تماس دقیق و قابل جست‌وجو باشد." },
  { icon: "brain" as const, title: "استخراج بینش", body: "موضوع، لحن، نتیجه و نکات مهم هر مکالمه برای بررسی مدیر آماده می‌شود." },
  { icon: "chart" as const, title: "سنجش کیفیت", body: "شاخص‌های ارزیابی، روند تیم و تماس‌های نیازمند توجه کنار هم قرار می‌گیرند." },
  { icon: "tasks" as const, title: "تعریف اقدام بعدی", body: "پیگیری‌های لازم ثبت می‌شوند تا بینش حاصل از تماس به بهبود قابل سنجش برسد." },
];

export default function Landing() {
  const [params, setParams] = useSearchParams();
  const annual = params.get("billing") === "annual";
  const [menuOpen, setMenuOpen] = useState(false);
  const [plans, setPlans] = useState<PublicPlan[]>([]);
  const [plansState, setPlansState] = useState<"loading" | "ready" | "error">("loading");
  function loadPlans() {
    setPlansState("loading");
    request<PublicPlan[]>("/v1/plans").then((items) => { setPlans(items); setPlansState("ready"); }).catch(() => setPlansState("error"));
  }
  useEffect(loadPlans, []);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuOpen]);
  function setBilling(value: string) {
    setParams((current) => { const next = new URLSearchParams(current); next.set("billing", value); return next; }, { replace: true });
  }
  return <div className="marketing-site" dir="rtl">
    <header className="site-header"><div className="site-container site-nav">
      <a href="#top" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></a>
      <nav id="site-navigation" className={menuOpen ? "site-links is-open" : "site-links"} aria-label="منوی اصلی">
        <a href="#features" onClick={() => setMenuOpen(false)}>امکانات</a><a href="#pricing" onClick={() => setMenuOpen(false)}>تعرفه‌ها</a><Link to="/about">درباره ما</Link><Link to="/contact">تماس با ما</Link>
      </nav>
      <div className="site-nav-actions"><Link className="site-button" to="/login">ورود به پنل</Link><button className="site-menu" aria-controls="site-navigation" aria-expanded={menuOpen} aria-label={menuOpen ? "بستن منو" : "باز کردن منو"} onClick={() => setMenuOpen(!menuOpen)}><Icon name={menuOpen ? "x" : "menu"}/></button></div>
    </div></header>
    <main id="top">
      <section className="site-hero" style={{ "--site-hero-art": `url(${heroBackdrop})` } as CSSProperties}><div className="site-container site-split">
        <div><h1>بدون صداسنج،<br/>هیچ تماسی واقعاً دیده نمی‌شود</h1><p>هر روز، فرصت‌های فروش و نشانه‌های نارضایتی در مکالمات پنهان می‌مانند. صداسنج آن‌ها را به اقدام روشن برای بهبود تجربه مشتری و عملکرد تیم تبدیل می‌کند.</p><div className="site-actions"><Link className="site-button" to="/signup?plan=demo">شروع رایگان</Link><a className="site-button site-button-outline" href="#features">مشاهده امکانات</a></div></div>
      </div></section>
      <section className="site-section" id="features"><div className="site-container"><h2>همه‌چیز برای درک بهتر تماس‌ها</h2><div className="site-benefits">{benefits.map((item) => <article key={item.title}><Icon name={item.icon} size={32}/><h3>{item.title}</h3><p>{item.body}</p></article>)}</div></div></section>
      <section className="site-section" id="workflow">
        <div className="site-container">
          <h2>از مکالمه تا اقدام</h2>
          <div className="workflow-timeline" aria-label="مسیر تبدیل تماس به اقدام مدیریتی">
            <svg className="timeline-art desktop-art" viewBox="0 0 1000 180" preserveAspectRatio="none" fill="none" aria-hidden="true">
              <defs><marker id="timeline-arrow-desktop" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M7 1 1 4l6 3"/></marker></defs>
              <path className="timeline-path desktop-path" d="M900 30 C820 30 800 126 700 126 S580 30 500 30 380 126 300 126 180 30 100 30" markerEnd="url(#timeline-arrow-desktop)"/>
              <path className="timeline-progress desktop-path" d="M900 30 C820 30 800 126 700 126 S580 30 500 30 380 126 300 126 180 30 100 30"/>
            </svg>
            <svg className="timeline-art mobile-art" viewBox="0 0 48 900" preserveAspectRatio="none" fill="none" aria-hidden="true">
              <defs><marker id="timeline-arrow-mobile" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="m1 1 3 6 3-6"/></marker></defs>
              <path className="timeline-path" d="M24 36 C24 100 8 154 24 221 S40 340 24 407 8 526 24 593 40 712 24 779" markerEnd="url(#timeline-arrow-mobile)"/>
              <path className="timeline-progress" d="M24 36 C24 100 8 154 24 221 S40 340 24 407 8 526 24 593 40 712 24 779"/>
            </svg>
            <ol className="site-steps">
              {steps.map((item) => <li key={item.title}><span className="timeline-node"><Icon name={item.icon} size={28}/></span><div><h3>{item.title}</h3><p>{item.body}</p></div></li>)}
            </ol>
          </div>
        </div>
      </section>
      <section className="site-section" id="pricing"><div className="site-container"><h2>پلن مناسب تیم شما</h2><p className="site-intro">قابلیت‌های اصلی مشترک؛ ظرفیت متناسب با نیاز تیم شما.</p><div className="site-billing" role="group" aria-label="دوره پرداخت"><button aria-pressed={!annual} onClick={() => setBilling("monthly")}>ماهانه</button><button aria-pressed={annual} onClick={() => setBilling("annual")}>سالانه</button></div>
        {plansState === "loading" && <p className="site-status" role="status">در حال دریافت پلن‌ها…</p>}
        {plansState === "error" && <div className="site-status" role="alert"><p>دریافت پلن‌ها انجام نشد.</p><button className="site-button site-button-outline" onClick={loadPlans}>تلاش دوباره</button></div>}
        {plansState === "ready" && !plans.length && <p className="site-status">در حال حاضر پلنی برای نمایش وجود ندارد.</p>}
        <div className="site-plans">{plans.map((plan) => { const demo = plan.code === "demo"; const price = annual ? plan.annual_price_toman : plan.monthly_price_toman; const extra = annual ? plan.extra_operator_annual_toman : plan.extra_operator_monthly_toman; return <article className={`site-plan${plan.code === "silver" ? " site-plan-featured" : ""}`} key={plan.code}><h3>{plan.name}</h3><p>{demo ? `${fmt.int(plan.trial_days ?? 7)} روز تجربه سامانه` : "همه امکانات اصلی صداسنج"}</p><div className="site-price"><strong>{demo ? "رایگان" : price == null ? "تماس بگیرید" : fmt.int(price)}</strong>{!demo && price != null && <span>تومان / {annual ? "سال" : "ماه"}</span>}</div><ul><li>{fmt.int(plan.base_operators)} کاربر اپراتور</li><li>{fmt.int(plan.assistant_monthly_messages)} پیام دستیار در ماه</li><li>{fmt.int(plan.intro_minutes)} دقیقه اعتبار {demo ? "تا پایان دمو" : "شروع، معتبر تا ۳۰ روز"}</li><li>هر دقیقه اضافه {fmt.toman(plan.overage_price_per_minute_toman)}</li>{plan.allows_extra_operators && extra != null && <li>اپراتور اضافه: {fmt.toman(extra)} / {annual ? "سال" : "ماه"}</li>}</ul><Link className={`site-button${plan.code === "silver" ? "" : " site-button-outline"}`} to={`/signup?plan=${encodeURIComponent(plan.code)}`}>شروع با پلن {plan.name}</Link></article>; })}</div>
        <p className="site-pricing-note">نصب اولیه رایگان است. برای استقرار اختصاصی <Link to="/contact">با ما تماس بگیرید.</Link></p>
      </div></section>
      <section className="site-section site-security" id="security"><div className="site-container"><h2>امنیت در تمام مراحل</h2><div className="site-benefits">{([{ icon: "shield", title: "حریم خصوصی", body: "فضای مستقل برای هر سازمان" }, { icon: "lock", title: "کنترل دسترسی", body: "دسترسی کاربران بر اساس نقش" }, { icon: "layers", title: "استقرار منعطف", body: "امکان استقرار اختصاصی سازمان" }] as typeof benefits).map((item) => <article key={item.title}><Icon name={item.icon} size={28}/><h3>{item.title}</h3><p>{item.body}</p></article>)}</div></div></section>
      <section className="site-cta"><div className="site-container"><h2>صدای مشتری را به تصمیم تبدیل کنید</h2><Link className="site-button" to="/signup?plan=demo">شروع رایگان</Link></div></section>
    </main>
    <footer className="site-footer"><div className="site-container"><img className="site-logo" src={logo} alt="صداسنج"/><nav aria-label="پیوندهای پایانی"><Link to="/contact">تماس با ما</Link><Link to="/terms">قوانین استفاده</Link><Link to="/privacy">حریم خصوصی</Link><Link to="/cancellation">لغو اشتراک</Link></nav><small>© ۱۴۰۵ صداسنج</small></div></footer>
  </div>;
}
