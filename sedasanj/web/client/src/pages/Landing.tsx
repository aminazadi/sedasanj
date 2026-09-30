import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import logo from "../assets/logo-small-fa.png";
import pattern from "../assets/pattern.png";
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

const wave = [20, 34, 48, 28, 62, 86, 44, 72, 36, 54, 96, 68, 42, 80, 58, 32, 74, 92, 48, 26, 60, 38, 76, 52, 30, 66, 44, 22];
const featureNumbers = ["۰۱", "۰۲", "۰۳", "۰۴", "۰۵", "۰۶", "۰۷", "۰۸"];
const features = [
  { icon: "message" as const, title: "متن دقیق مکالمه", body: "تبدیل خودکار صوت فارسی به متن، با تفکیک صحبت‌های مشتری و اپراتور و دسترسی سریع به هر لحظه از تماس." },
  { icon: "brain" as const, title: "تحلیل هوشمند محتوا", body: "استخراج موضوع، نتیجه، نیاز مشتری و نکات کلیدی هر تماس؛ بدون نیاز به شنیدن ساعت‌ها فایل صوتی." },
  { icon: "pulse" as const, title: "درک لحن و احساس", body: "بررسی فراز و فرود مکالمه و شناسایی لحظات مثبت، خنثی یا پرتنش در صدای مشتری و اپراتور." },
  { icon: "target" as const, title: "ارزیابی عملکرد", body: "امتیازدهی یکپارچه به اپراتورها و مشاهده روند کیفیت مکالمات در بازه‌های زمانی مختلف." },
  { icon: "chart" as const, title: "داشبورد مدیریتی", body: "شاخص‌های مهم، تماس‌های نیازمند توجه و روند تیم را در یک نمای شفاف و قابل تصمیم‌گیری ببینید." },
  { icon: "layers" as const, title: "اتصال به مرکز تماس", body: "دریافت امن تماس‌ها از زیرساخت تلفنی و تحویل نتیجه از طریق پنل، API و وب‌هوک امضاشده." },
  { icon: "tasks" as const, title: "اقدام‌های بعد از تماس", body: "اقدام‌های بعدی استخراج‌شده از هر تماس را با زمان سررسید و وضعیت انجام در یک فهرست متمرکز مدیریت کنید." },
  { icon: "spark" as const, title: "دستیار هوشمند سازمان", body: "درباره تماس‌ها، تحلیل‌ها و عملکرد اپراتورها سؤال کنید و از میان داده‌های واقعی سازمان پاسخ سریع و مستند بگیرید." },
];

function DashboardPreview() {
  return <div className="landing-preview" aria-label="پیش‌نمای داشبورد تحلیل تماس">
    <div className="preview-topbar"><div className="preview-dots"><i/><i/><i/></div><span>نمای تماس</span><span className="preview-live"><i/> تحلیل‌شده</span></div>
    <div className="preview-body">
      <div className="preview-call-row"><div className="preview-avatar"><Icon name="headset" size={22}/></div><div><strong>مکالمه با مشتری</strong><span>امروز، ۱۰:۴۲ · ۰۳:۱۸ دقیقه</span></div><span className="preview-phone" aria-hidden="true"><Icon name="phone" size={17}/></span></div>
      <div className="waveform" aria-hidden="true">{wave.map((height, index) => <i key={index} style={{ height: `${height}%`, animationDelay: `${index * 35}ms` }}/>)}</div>
      <div className="preview-grid">
        <div className="quality-card"><div className="quality-ring"><span>۸۹</span><small>امتیاز</small></div><div><span>کیفیت مکالمه</span><strong><Icon name="trend" size={16}/> عالی</strong></div></div>
        <div className="sentiment-card"><span>لحن غالب</span><strong><i/> مثبت</strong><small>رضایت مشتری در پایان تماس افزایش یافته است.</small></div>
      </div>
      <div className="preview-summary"><div><span className="ai-spark"><Icon name="spark" size={16}/></span><strong>خلاصه هوشمند</strong><small>آماده در کمتر از یک دقیقه</small></div><p>مشتری برای پیگیری سفارش تماس گرفت. اپراتور وضعیت ارسال را بررسی و زمان دقیق تحویل را اعلام کرد.</p><div className="preview-tags"><span>پیگیری سفارش</span><span>حل‌شده</span><span>رضایت بالا</span></div></div>
    </div>
  </div>;
}

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [annual, setAnnual] = useState(false);
  const [plans, setPlans] = useState<PublicPlan[]>([]);
  const [plansError, setPlansError] = useState(false);

  useEffect(() => {
    request<PublicPlan[]>("/v1/plans")
      .then(setPlans)
      .catch(() => setPlansError(true));
  }, []);

  useEffect(() => {
    const elements = document.querySelectorAll(".landing-reveal:not(.is-visible)");
    if (elements.length === 0) return;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12 });
    elements.forEach((element) => observer.observe(element));
    return () => observer.disconnect();
  }, [plans]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => event.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuOpen]);

  return <div className="landing" dir="rtl">
    <header className="landing-header"><div className="landing-container landing-nav">
      <a className="landing-brand" href="#top" aria-label="صداسنج، صفحه اصلی"><img src={logo} alt="صداسنج" /></a>
      <nav className={menuOpen ? "landing-links is-open" : "landing-links"} aria-label="دسترسی اصلی">
        <a href="#features" onClick={() => setMenuOpen(false)}>امکانات</a><a href="#pricing" onClick={() => setMenuOpen(false)}>پلن‌ها</a><Link to="/about">درباره ما</Link><Link to="/contact">تماس با ما</Link><Link className="mobile-login-link" to="/login">ورود به پنل <Icon name="arrow" size={18}/></Link>
      </nav>
      <div className="landing-nav-actions"><Link className="landing-login" to="/login">ورود به پنل <Icon name="arrow" size={18}/></Link><button className="landing-menu" type="button" aria-label={menuOpen ? "بستن فهرست" : "باز کردن فهرست"} aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}><Icon name={menuOpen ? "x" : "menu"}/></button></div>
    </div></header>

    <main id="top">
      <section className="landing-hero" style={{ "--landing-pattern": `url(${pattern})` } as React.CSSProperties}>
        <div className="hero-glow hero-glow-one"/><div className="hero-glow hero-glow-two"/>
        <div className="landing-container hero-grid">
          <div className="hero-copy"><div className="hero-eyebrow"><span><Icon name="spark" size={17}/></span>هوش مصنوعی برای مکالمات واقعی</div><h1>از هر تماس،<br/><em>یک تصمیم بهتر</em> بسازید.</h1><p>صداسنج، مکالمات مرکز تماس شما را می‌شنود، می‌فهمد و به بینشی روشن برای بهبود تجربه مشتری و عملکرد تیم تبدیل می‌کند.</p><div className="hero-actions"><Link className="landing-primary" to="/login">ورود به سامانه <Icon name="arrow" size={20}/></Link><a className="landing-secondary" href="#features">کشف امکانات <Icon name="chevron" size={19}/></a></div><div className="hero-trust"><span><Icon name="check" size={16}/> تحلیل فارسی</span><span><Icon name="check" size={16}/> راه‌اندازی سازمانی</span><span><Icon name="check" size={16}/> اتصال امن</span></div></div>
          <div className="hero-visual"><div className="visual-orbit orbit-one"/><div className="visual-orbit orbit-two"/><DashboardPreview/><div className="floating-card floating-sentiment"><span><Icon name="pulse" size={18}/></span><div><small>احساس مشتری</small><strong>رضایتمند</strong></div></div><div className="floating-card floating-insight"><span><Icon name="spark" size={18}/></span><div><small>بینش جدید</small><strong>فرصت پیگیری شناسایی شد</strong></div></div></div>
        </div>
        <div className="landing-container capability-strip"><span>از صدا تا بینش، در یک جریان یکپارچه</span><div><b>صوت تماس</b><i/><b>متن فارسی</b><i/><b>تحلیل هوشمند</b><i/><b>اقدام مؤثر</b></div></div>
      </section>

      <section className="landing-section problem-section" id="results"><div className="landing-container problem-grid landing-reveal"><div className="section-heading"><span>چرا صداسنج؟</span><h2>صدای مشتریان شما،<br/>پر از پاسخ است.</h2></div><div className="problem-copy"><p>در میان صدها ساعت مکالمه، نشانه‌های نارضایتی، فرصت‌های فروش و الگوهای عملکرد پنهان می‌مانند. صداسنج این حجم از صدا را به اطلاعاتی تبدیل می‌کند که بتوانید همان روز از آن استفاده کنید.</p><div className="value-list"><span><Icon name="clock"/> زمان کمتر برای پایش تماس‌ها</span><span><Icon name="target"/> ارزیابی منصفانه‌تر تیم</span><span><Icon name="trend"/> تصمیم‌گیری بر پایه داده واقعی</span></div></div></div></section>

      <section className="landing-section features-section" id="features"><div className="landing-container"><div className="section-heading centered landing-reveal"><span>تصویر کامل هر مکالمه</span><h2>همه‌چیز برای شنیدن، فهمیدن و بهبود</h2><p>از متن تماس تا روند عملکرد تیم، تمام اطلاعاتی که برای مدیریت تجربه مشتری نیاز دارید در یک محیط منسجم کنار هم قرار می‌گیرد.</p></div><div className="feature-grid">{features.map((feature, index) => <article className={`feature-card landing-reveal feature-${index + 1}`} key={feature.title}><div className="feature-icon"><Icon name={feature.icon}/></div><h3>{feature.title}</h3><p>{feature.body}</p><span className="feature-number">{featureNumbers[index]}</span></article>)}</div></div></section>

      <section className="landing-section product-tools-section"><div className="landing-container product-tools-grid"><div className="product-tool-card tasks-tool landing-reveal"><div className="tool-card-copy"><span><Icon name="tasks" size={18}/> بعد از هر تماس</span><h2>هیچ قول یا اقدام بعدی<br/>فراموش نمی‌شود.</h2><p>صداسنج کارهای قابل پیگیری را از دل مکالمه بیرون می‌کشد تا تیم بداند چه کاری و تا چه زمانی باید انجام شود.</p><ul><li><Icon name="check" size={16}/> مشاهده همه کارها در یک فهرست</li><li><Icon name="check" size={16}/> اتصال مستقیم هر کار به تماس</li><li><Icon name="check" size={16}/> مدیریت وضعیت و سررسید</li></ul></div><div className="tasks-preview"><div className="tasks-preview-head"><strong>اقدام‌های بعدی</strong><span>۳ مورد باز</span></div><div className="task-row"><i className="task-check"/><div><strong>ارسال پیش‌فاکتور برای مشتری</strong><small>امروز · تماس فروش</small></div><b>فوری</b></div><div className="task-row"><i className="task-check is-done"><Icon name="check" size={13}/></i><div><strong>بررسی وضعیت ارسال سفارش</strong><small>انجام‌شده · پشتیبانی</small></div></div><div className="task-row"><i className="task-check"/><div><strong>تماس مجدد برای تمدید قرارداد</strong><small>فردا · پیگیری</small></div><b className="normal">عادی</b></div></div></div><div className="product-tool-card assistant-tool landing-reveal"><div className="tool-card-copy"><span><Icon name="spark" size={18}/> دستیار هوشمند سازمان</span><h2>پاسخ را از میان<br/>مکالمات واقعی پیدا کنید.</h2><p>به‌جای جست‌وجوی دستی، سؤال خود را بپرسید و بر پایه متن تماس‌ها، تحلیل‌ها و امتیاز اپراتورها پاسخ بگیرید.</p></div><div className="assistant-preview"><div className="assistant-question">کدام موضوع بیشترین نارضایتی را در این ماه ایجاد کرده؟</div><div className="assistant-answer"><span><Icon name="spark" size={17}/></span><p>در تماس‌های مرتبط، <strong>تأخیر در تحویل سفارش</strong> پرتکرارترین موضوع نارضایتی شناسایی شده است.</p></div><div className="assistant-sources"><span>تماس‌های مرتبط</span><span>تحلیل عملکرد تیم</span></div></div></div></div></section>

      <section className="landing-section workflow-section" id="workflow"><div className="landing-container workflow-grid"><div className="workflow-visual landing-reveal"><div className="workflow-card workflow-call"><span><Icon name="phone"/></span><div><small>تماس ورودی</small><strong>مکالمه ثبت شد</strong></div><i className="status-dot"/></div><div className="workflow-line"><i/><i/><i/><i/><i/></div><div className="workflow-card workflow-ai"><span><Icon name="brain"/></span><div><small>پردازش هوشمند</small><strong>تحلیل متن، لحن و نتیجه</strong></div><b>AI</b></div><div className="workflow-report"><div><span>امتیاز مکالمه</span><strong>۹۲</strong></div><div className="mini-bars"><i style={{height:"45%"}}/><i style={{height:"68%"}}/><i style={{height:"56%"}}/><i style={{height:"82%"}}/><i style={{height:"72%"}}/><i style={{height:"94%"}}/></div><small><Icon name="trend" size={14}/> ۱۲٪ بهبود نسبت به دوره قبل</small></div></div><div className="workflow-copy landing-reveal"><div className="section-heading"><span>ساده و خودکار</span><h2>سه قدم تا درک کامل هر تماس</h2></div><ol className="workflow-steps"><li><b>۱</b><div><h3>اتصال و دریافت امن</h3><p>تماس‌ها به‌شکل خودکار از مرکز تماس دریافت و برای پردازش آماده می‌شوند.</p></div></li><li><b>۲</b><div><h3>پردازش چندلایه</h3><p>صوت به متن تبدیل می‌شود و محتوا، لحن و کیفیت مکالمه هم‌زمان تحلیل می‌شوند.</p></div></li><li><b>۳</b><div><h3>خروجی آماده تصمیم</h3><p>خلاصه، امتیازها و نکات مهم در داشبورد قرار می‌گیرند تا تصمیم بعدی روشن باشد.</p></div></li></ol></div></div></section>

      <section className="landing-section quote-section"><div className="landing-container"><div className="quote-card landing-reveal"><Icon name="quote" size={42}/><blockquote>مدیریت مرکز تماس فقط شنیدن مکالمه نیست؛ دیدن الگوهایی است که کیفیت ارتباط با مشتری را نشان می‌دهند.</blockquote><p>صداسنج این الگوها را از دل هر مکالمه بیرون می‌آورد.</p></div></div></section>

      <section className="landing-section pricing-section" id="pricing"><div className="landing-container"><div className="section-heading centered landing-reveal"><span>پلن‌های متناسب با اندازه تیم</span><h2>شفاف شروع کنید و با رشد تیم، ظرفیت را بیشتر کنید</h2><p>همه پلن‌های پولی قابلیت‌های اصلی یکسان دارند و تفاوت آن‌ها در ظرفیت اپراتور، سهمیه دستیار و اعتبار شروع همکاری است.</p></div><div className="billing-toggle landing-reveal"><button className={!annual ? "active" : ""} onClick={() => setAnnual(false)}>ماهانه</button><button className={annual ? "active" : ""} onClick={() => setAnnual(true)}>سالانه <b>۲ ماه تخفیف</b></button></div><div className="pricing-rate landing-reveal"><div><span><Icon name="pulse" size={20}/></span><p>تعرفه پردازش</p><strong>هر دقیقه ۲٬۰۰۰ تومان</strong></div><small>اعتبار اضافه پیش‌پرداخت است و منقضی نمی‌شود</small></div>{plansError ? <div className="plans-unavailable">اطلاعات پلن‌ها در حال حاضر در دسترس نیست.</div> : null}<div className="pricing-grid">{plans.map((plan) => { const price = plan.code === "demo" ? 0 : annual ? plan.annual_price_toman ?? 0 : plan.monthly_price_toman; const extraPrice = annual ? plan.extra_operator_annual_toman : plan.extra_operator_monthly_toman; return <article className={plan.code === "silver" ? "pricing-card is-featured landing-reveal" : "pricing-card landing-reveal"} key={plan.code}>{plan.code === "silver" ? <span className="popular-badge">پیشنهاد صداسنج</span> : null}<div className="plan-heading"><div><h3>{plan.name}</h3><p>{plan.code === "demo" ? `${fmt.int(plan.trial_days ?? 7)} روز تجربه سامانه` : "همه امکانات اصلی صداسنج"}</p></div><span className="plan-dot"/></div><div className="plan-price"><strong>{plan.code === "demo" ? "رایگان" : fmt.int(price)}</strong>{plan.code !== "demo" ? <span>تومان / {annual ? "سال" : "ماه"}</span> : null}</div><ul><li><Icon name="users" size={18}/>{plan.base_operators ? `${fmt.int(plan.base_operators)} کاربر اپراتور` : "بدون سهمیه اپراتور"}</li>{plan.allows_extra_operators && extraPrice ? <li><Icon name="users" size={18}/>هر اپراتور اضافه {fmt.toman(extraPrice)} / {annual ? "سال" : "ماه"}</li> : null}<li><Icon name="spark" size={18}/>{fmt.int(plan.assistant_monthly_messages)} پیام دستیار در ماه</li><li><Icon name="clock" size={18}/>{plan.code === "demo" ? `${fmt.int(plan.intro_minutes)} دقیقه تحلیل تا پایان دمو` : `اعتبار شروع: ${fmt.int(plan.intro_minutes)} دقیقه، معتبر تا ۳۰ روز`}</li><li><Icon name="pulse" size={18}/>هر دقیقه اضافه {fmt.toman(plan.overage_price_per_minute_toman)}</li></ul><Link to={`/signup?plan=${plan.code}`}>شروع با پلن {plan.name}<Icon name="arrow" size={18}/></Link></article>; })}</div><div className="pricing-footer landing-reveal"><div><span><Icon name="layers"/></span><div><strong>نصب و راه‌اندازی</strong><p>نصب اولیه رایگان است · نصب مجدد ۳٬۰۰۰٬۰۰۰ تومان</p></div></div><div><span><Icon name="headset"/></span><div><strong>نصب اختصاصی</strong><p>استقرار اختصاصی ۲۰٬۰۰۰٬۰۰۰ تومان است؛ برای ثبت درخواست با ما تماس بگیرید.</p></div></div></div></div></section>

      <section className="landing-section security-section" id="security"><div className="landing-container security-grid"><div className="security-copy landing-reveal"><div className="section-heading"><span>ساخته‌شده برای سازمان‌ها</span><h2>معماری مطمئن<br/>برای داده‌های حساس</h2><p>از انتقال فایل تا دسترسی کاربران و تحویل نتایج، امنیت در تمام مسیر تحلیل مکالمه در نظر گرفته شده است.</p></div><div className="security-points"><span><Icon name="shield"/> کنترل دسترسی مبتنی بر نقش</span><span><Icon name="lock"/> انتقال و نگهداری امن داده</span><span><Icon name="users"/> فضای مستقل برای هر سازمان</span></div></div><div className="security-visual landing-reveal"><div className="shield-rings"><i/><i/><i/><span><Icon name="shield" size={48}/></span></div><div className="security-badge badge-one"><Icon name="lock" size={18}/><span>اتصال امن</span></div><div className="security-badge badge-two"><Icon name="check" size={18}/><span>دسترسی کنترل‌شده</span></div><div className="security-badge badge-three"><Icon name="layers" size={18}/><span>استقرار منعطف</span></div></div></div></section>

      <section className="landing-section cta-section"><div className="landing-container"><div className="cta-card landing-reveal" style={{ "--landing-pattern": `url(${pattern})` } as React.CSSProperties}><div><span><Icon name="spark" size={17}/> شروع یک نگاه تازه</span><h2>اجازه ندهید هیچ نکته‌ای<br/>در مکالمات گم شود.</h2><p>با صداسنج، صدای مشتری را به مسیری روشن برای بهبود تبدیل کنید.</p></div><Link className="cta-button" to="/login">ورود به سامانه <Icon name="arrow" size={20}/></Link></div></div></section>
    </main>

    <footer className="landing-footer"><div className="landing-container footer-row"><img src={logo} alt="صداسنج"/><p>سامانه هوشمند تحلیل مکالمات فارسی</p><div><a href="#features">امکانات</a><a href="#pricing">پلن‌ها</a><Link to="/about">درباره ما</Link><Link to="/contact">تماس با ما</Link><Link to="/terms">قوانین</Link><Link to="/privacy">حریم خصوصی</Link><Link to="/cancellation">لغو</Link><Link to="/login">ورود</Link></div><small>© ۱۴۰۵ صداسنج</small></div></footer>
  </div>;
}
