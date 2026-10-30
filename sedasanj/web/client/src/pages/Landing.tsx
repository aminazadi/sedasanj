import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import logo from "../assets/sedasanj-refined-master.svg";
import heroBackdrop from "../assets/hero-call-center.webp";
import integrationBanner from "../assets/telephony-integration-banner-desktop.webp";
import integrationBannerMobile from "../assets/telephony-integration-banner-mobile.webp";
import awarenessArt from "../assets/operator-awareness.svg";
import ucGov from "../assets/usecases/gov.svg";
import ucFinance from "../assets/usecases/finance.svg";
import ucHealth from "../assets/usecases/health.svg";
import ucSales from "../assets/usecases/sales.svg";
import ucSupport from "../assets/usecases/support.svg";
import ucCommerce from "../assets/usecases/commerce.svg";
import planDemoImage from "../assets/plan-demo.webp";
import planBronzeImage from "../assets/plan-bronze.webp";
import planSilverImage from "../assets/plan-silver.webp";
import planGoldImage from "../assets/plan-gold.webp";
import "./Landing.css";
import { fmt, request, SENTIMENT_LABELS } from "../api";
import type { PublicPlan } from "../types";
import QuickDemoEntry from "../components/QuickDemoEntry";
import WhyVideoButton from "../components/WhyVideoButton";
import { Icon, type IconName } from "../components/SiteIcon";

const benefits: Array<{ icon: IconName; title: string; body: string }> = [
  { icon: "chart", title: "داشبورد و گزارش‌های مدیریتی", body: "حجم تماس‌ها، روند کیفیت پاسخ‌گویی و وضعیت عملکرد تیم را در یک نگاه بررسی کنید و گزارش‌ها را بر اساس بازه زمانی و اپراتور فیلتر کنید." },
  { icon: "target", title: "ارزیابی کیفیت و عملکرد اپراتورها", body: "مکالمات را با معیارهای ارزیابی سازمان امتیازدهی کنید؛ عملکرد اپراتورها را مقایسه کنید و نقاط قوت و نیازهای آموزشی تیم را بشناسید." },
  { icon: "message", title: "متن و خلاصه قابل جست‌وجوی تماس‌ها", body: "به متن فارسی، خلاصه و نکات کلیدی مکالمات دسترسی داشته باشید؛ بدون شنیدن تمام فایل صوتی، جزئیات موردنیاز برای بررسی هر تماس را پیدا کنید." },
  { icon: "pulse", title: "تحلیل موضوع، احساس و نتیجه تماس", body: "موضوعات پرتکرار، لحن مشتری و نتیجه مکالمات را بررسی کنید تا دلایل نارضایتی و تماس‌های نیازمند توجه مدیر را شناسایی کنید." },
  { icon: "tasks", title: "مدیریت پیگیری‌ها و تعهدات", body: "اقدام‌های بعدی استخراج‌شده از مکالمات را همراه با وضعیت و سررسید مدیریت کنید و برای بررسی جزئیات، مستقیماً به تماس مرتبط برگردید." },
  { icon: "headset", title: "دستیار هوشمند سازمان", body: "درباره تماس‌ها، تحلیل‌ها و عملکرد اپراتورها سؤال بپرسید و پاسخ مستند به داده‌های سازمان را همراه با ارجاع به مکالمات مرتبط دریافت کنید." },
];

type UseCase = { id: string; icon: IconName; label: string; title: string; body: string; source?: { label: string; url?: string } };
const useCases: UseCase[] = [
  { id: "gov", icon: "shield", label: "سازمان‌های دولتی", title: "پیش از آنکه شکایت به بازرسی برسد", body: "سازمان بازرسی کل کشور سالانه حدود ۱۰۰ هزار شکایت و گزارش از سامانهٔ ۱۳۶ دریافت می‌کند. اگر مدیر دستگاه بداند کدام موضوع و کدام واحد بیشترین تماس پیگیری را می‌سازد، گره را پیش از تبدیل‌شدن تماس به شکایت باز می‌کند؛ آن هم روی سرور خود سازمان.", source: { label: "سخنان رئیس سازمان بازرسی کل کشور، اختبار", url: "https://www.ekhtebar.ir/امکان-ثبت-شکایت-از-عملکرد-دستگاهها/" } },
  { id: "finance", icon: "lock", label: "بانک، بیمه و مالی", title: "پیش از شکایت رسمی، تماس را بشنوید", body: "بیمهٔ مرکزی در نُه ماههٔ نخست ۱۴۰۳ بیش از ۵٬۸۰۰ شکایت از شرکت‌های بیمه ثبت کرده است. مدیر شعبه‌ای که قولی به مشتری داده و پیگیری نشده، نخستین حلقهٔ همین مسیر است؛ صداسنج تعهدها، سررسیدها و تماس‌های پرریسک را پیش از رسیدن به شکایت نشان می‌دهد.", source: { label: "آمار بیمهٔ مرکزی ایران، بازنشر در رسانه‌های بیمه‌ای" } },
  { id: "health", icon: "pulse", label: "درمان و کلینیک‌ها", title: "هر نوبتِ خالی، هزینه‌ای است که دیده نمی‌شود", body: "در مطالعه‌ای روی کلینیک‌های سرپایی یک بیمارستان در تهران، حدود ۵۰ درصد نوبت‌ها بدون مراجعهٔ بیمار ماند. مدیر کلینیکی که دلیل لغو و ساعت‌های شلوغ تماس پذیرش را از متن تماس‌ها ببیند، یادآوری و ظرفیت نوبت را بر پایهٔ داده تنظیم می‌کند.", source: { label: "پژوهش Missed Appointments، بیمارستان‌های سرپایی تهران", url: "https://repository.brieflands.com/items/acabd84f-3dd1-4c7e-abab-7aa1420bd9ca" } },
  { id: "sales", icon: "trend", label: "فروش و بازاریابی", title: "ساعت اول تعیین می‌کند فروش بماند یا برود", body: "پژوهش هاروارد بیزینس ریویو نشان داد شرکت‌هایی که ظرف یک ساعت به سرنخ آنلاین پاسخ می‌دهند، حدود هفت برابر بیشتر احتمال دارد آن را به مشتری بالقوهٔ واجد شرایط تبدیل کنند. صداسنج تماس‌های آمادهٔ خرید را که هنوز پیگیری نشده‌اند به مدیر فروش نشان می‌دهد.", source: { label: "Harvard Business Review، «The Short Life of Online Sales Leads»", url: "https://scholarsarchive.byu.edu/facpub/9711" } },
  { id: "support", icon: "headset", label: "پشتیبانی و پس از فروش", title: "سومین تماس برای یک خرابی، فقط یک تماس نیست", body: "مشتری برای بار سوم دربارهٔ همان خرابی زنگ می‌زند و هر بار با کارشناسی تازه از صفر شروع می‌کند. صداسنج تماس‌های تکراری و بدترشدن لحن مشتری را کنار هم نشان می‌دهد تا مدیر پشتیبانی به‌جای پاسخ دوباره، علت ریشه‌ای را رفع کند." },
  { id: "commerce", icon: "message", label: "فروشگاه و خدمات آنلاین", title: "سفارش دیر می‌رسد؛ مشتری اول زنگ می‌زند", body: "مشتری دو بار وضعیت سفارش را پرسیده و هنوز پاسخ روشنی نگرفته است. پیش از آنکه سفارش مرجوع شود یا مشتری برود، صداسنج از دل همین تماس‌ها نشان می‌دهد ارسال یا مرجوعی در کدام مرحله گیر کرده است." },
];
const steps = [
  { icon: "phone" as const, title: "دریافت امن تماس", body: "تماس‌های مرکز تلفن به‌صورت خودکار و همراه با اطلاعات لازم وارد جریان تحلیل می‌شوند." },
  { icon: "message" as const, title: "تبدیل گفتار به متن", body: "گفت‌وگوی مشتری و اپراتور تفکیک می‌شود تا محتوای تماس دقیق و قابل جست‌وجو باشد." },
  { icon: "brain" as const, title: "استخراج بینش", body: "موضوع، لحن، نتیجه و نکات مهم هر مکالمه برای بررسی مدیر آماده می‌شود." },
  { icon: "chart" as const, title: "سنجش کیفیت", body: "شاخص‌های ارزیابی، روند تیم و تماس‌های نیازمند توجه کنار هم قرار می‌گیرند." },
  { icon: "tasks" as const, title: "تعریف اقدام بعدی", body: "پیگیری‌های لازم ثبت می‌شوند تا بینش حاصل از تماس به بهبود قابل سنجش برسد." },
];

const planArt: Record<string, { className: string; image: string }> = {
  demo: { className: "plan-art-demo", image: planDemoImage },
  bronze: { className: "plan-art-bronze", image: planBronzeImage },
  silver: { className: "plan-art-silver", image: planSilverImage },
  gold: { className: "plan-art-gold", image: planGoldImage },
};

function PlanArtwork({ code, name }: { code: string; name: string }) {
  const art = planArt[code] ?? planArt.bronze;
  return <img className={`site-plan-art ${art.className}`} src={art.image} alt={`تصویر پلن ${name}`} loading="lazy" decoding="async" />;
}

function AnimatedPrice({ value, formatted }: { value: number | null; formatted: string }) {
  const [display, setDisplay] = useState(formatted);
  const currentValue = useRef<number | null>(value);
  useEffect(() => {
    if (value == null || currentValue.current == null || value === currentValue.current) {
      currentValue.current = value;
      setDisplay(formatted);
      return;
    }
    const from = currentValue.current;
    const to = value;
    const duration = 650;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - (1 - progress) ** 3;
      setDisplay(fmt.int(Math.round(from + (to - from) * eased)));
      if (progress < 1) frame = requestAnimationFrame(tick);
      else { currentValue.current = to; setDisplay(formatted); }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, formatted]);
  return <strong aria-live="polite">{display}</strong>;
}


const ucPhotos: Record<string, { src: string; alt: string }> = {
  gov: { src: ucGov, alt: "طراحی خطی ساختمان دولتی و سرور اختصاصی در محدودهٔ امن سازمان" },
  finance: { src: ucFinance, alt: "طراحی خطی مکالمهٔ تلفنی و قراردادی که بند پرریسک آن علامت خورده است" },
  health: { src: ucHealth, alt: "طراحی خطی تقویم نوبت‌دهی کلینیک و مکالمهٔ تلفنی" },
  sales: { src: ucSales, alt: "طراحی خطی مکالمهٔ فروش که به هدف خرید می‌رسد" },
  support: { src: ucSupport, alt: "طراحی خطی هدست پشتیبانی و تیکت تکراری با سه بار تماس" },
  commerce: { src: ucCommerce, alt: "طراحی خطی بستهٔ سفارش در مسیر ارسال و پرسش مشتری دربارهٔ پیگیری" },
};
const ucNodes = useCases.map((_, i) => {
  const angle = (-90 + (360 / useCases.length) * i) * (Math.PI / 180);
  const x = 50 + 38 * Math.cos(angle);
  const y = 50 + 38 * Math.sin(angle);
  const mx = (50 + x) / 2 - Math.sin(angle) * 7;
  const my = (50 + y) / 2 + Math.cos(angle) * 7;
  return { x, y, d: `M50 50 Q${mx.toFixed(2)} ${my.toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)}` };
});

function UseCases() {
  const [active, setActive] = useState(0);
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const current = useCases[active];
  function onKey(event: ReactKeyboardEvent, index: number) {
    const last = useCases.length - 1;
    const forward = event.key === "ArrowDown" || event.key === "ArrowLeft";
    const back = event.key === "ArrowUp" || event.key === "ArrowRight";
    const next = forward ? (index === last ? 0 : index + 1) : back ? (index === 0 ? last : index - 1) : event.key === "Home" ? 0 : event.key === "End" ? last : -1;
    if (next < 0) return;
    event.preventDefault();
    setActive(next);
    refs.current[next]?.focus();
  }
  return <section className="site-section site-usecases" id="usecases">
    <div className="site-container">
      <h2>مشتری‌تان چیزی می‌گوید که فقط تلفن می‌شنود</h2>
      <p className="site-intro">صداسنج آن را می‌شنود و به تصمیم برای شما تبدیل می‌کند.</p>
      <div className="uc-stage">
        <div className="uc-orbit" role="tablist" aria-label="حوزه‌های کاربرد صداسنج" aria-orientation="vertical">
          <svg className="uc-branches" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
            {ucNodes.map((n, i) => <path key={useCases[i].id} d={n.d} pathLength={1} className="uc-branch"/>)}
            <path key={`on-${current.id}`} d={ucNodes[active].d} pathLength={1} className="uc-branch uc-branch-on"/>
            <g key={`pulse-${current.id}`} className="uc-flow"><circle r="1.5" className="uc-flow-dot"/><circle r="1.5" className="uc-flow-ring"><animate attributeName="r" values="1.5;5" dur="1.1s" repeatCount="indefinite"/><animate attributeName="opacity" values=".6;0" dur="1.1s" repeatCount="indefinite"/></circle><animateMotion dur="2.2s" repeatCount="indefinite" path={ucNodes[active].d}/></g>
          </svg>
          <div className="uc-core" aria-hidden="true"><span className="uc-ring"/><span className="uc-ring uc-ring-late"/><svg className="uc-pulse" viewBox="0 0 24 24" width="44" height="44" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path className="uc-pulse-base" d="M2 12h5l2-7 4 14 2-7h7" pathLength={1}/><path className="uc-pulse-beat" d="M2 12h5l2-7 4 14 2-7h7" pathLength={1}/></svg></div>
          {useCases.map((item, index) => <button key={item.id} ref={(el) => { refs.current[index] = el; }} type="button" role="tab" id={`usecase-tab-${item.id}`} aria-selected={index === active} aria-controls="usecase-panel" tabIndex={index === active ? 0 : -1} className={`uc-node${ucNodes[index].y < 45 ? " is-above" : ""}${index === active ? " is-active" : ""}`} style={{ left: `${ucNodes[index].x}%`, top: `${ucNodes[index].y}%` }} onClick={() => setActive(index)} onMouseEnter={() => setActive(index)} onKeyDown={(event) => onKey(event, index)}>
            <span className="uc-node-dot"><img src={ucPhotos[item.id].src} alt={ucPhotos[item.id].alt} width={120} height={120} loading="lazy" decoding="async"/></span><span className="uc-node-label">{item.label}</span>
          </button>)}
        </div>
        <div className="uc-bubble" role="tabpanel" id="usecase-panel" aria-labelledby={`usecase-tab-${current.id}`} key={current.id}>
          <img className="uc-bg" src={ucPhotos[current.id].src} alt="" aria-hidden="true" width={120} height={120} decoding="async"/>
          <h3>{current.title}</h3>
          <p>{current.body}</p>
          {current.source ? <small className="uc-source">منبع: {current.source.url ? <a href={current.source.url} target="_blank" rel="noreferrer">{current.source.label}</a> : current.source.label}</small> : null}
        </div>
      </div>
    </div>
  </section>;
}

const SAT_ORDER = ["happy", "satisfied", "neutral", "sad", "angry"] as const;
const SAT_EMOJI: Record<string, string> = { angry: "😡", sad: "😢", neutral: "😐", satisfied: "🙂", happy: "😄" };
const SAT_TONES: Record<string, string> = { happy: "#176b34", satisfied: "#1c5aa3", neutral: "#4a5059", sad: "#b04a07", angry: "#b42318" };
// Illustrative call counts per sentiment. The first picture has neutral and sad on top; afterwards a different sentiment leads on every tick.
const SAT_START = [118, 162, 436, 318, 64];
function nextSatCounts(previous: number[]): number[] {
  const lead = (previous.indexOf(Math.max(...previous)) + 1 + Math.floor(Math.random() * (SAT_ORDER.length - 1))) % SAT_ORDER.length;
  return SAT_ORDER.map((_, i) => (i === lead ? 380 + Math.floor(Math.random() * 90) : 60 + Math.floor(Math.random() * 230)));
}

function CountNumber({ value, format = fmt.int }: { value: number; format?: (value: number) => string }) {
  const [shown, setShown] = useState(0);
  const from = useRef(0);
  useEffect(() => {
    const start = performance.now();
    const origin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min((now - start) / 1100, 1);
      const next = origin + (value - origin) * (1 - (1 - progress) ** 3);
      from.current = next;
      setShown(next);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <>{format(shown)}</>;
}

function SatisfactionShowcase() {
  const ref = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const [values, setValues] = useState(SAT_START);
  const calm = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") { setVisible(true); return; }
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), { threshold: 0.35 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible || calm) return;
    const timer = window.setInterval(() => setValues(nextSatCounts), 3800);
    return () => window.clearInterval(timer);
  }, [visible, calm]);
  useEffect(() => { if (!visible) setValues(SAT_START); }, [visible]);
  const counts = visible ? values : SAT_START.map(() => 0);
  const total = counts.reduce((sum, count) => sum + count, 0);
  const top = counts.indexOf(Math.max(...counts));
  return <section className="site-section site-satisfaction" id="satisfaction" ref={ref}>
    <div className="site-container">
      <h2>پیش‌نمایشی از رضایت مشتریان شما</h2>
      <p className="site-intro">همان نمایی که مدیر و اپراتورها در داشبورد صداسنج می‌بینند: احساس مشتری در هر تماس تحلیل و از «عصبانی» تا «خوشحال» شمرده می‌شود.</p>
      <div className="sat-grid">
        {SAT_ORDER.map((key, i) => <div className="sat-item" key={key} style={{ "--sat-tone": SAT_TONES[key] } as CSSProperties}>
          <span className={`sat-emoji${i === top && visible ? " is-top" : ""}`} role="img" aria-label={SENTIMENT_LABELS[key]}>{SAT_EMOJI[key]}</span>
          <strong className="sat-count"><CountNumber value={counts[i]}/></strong>
          <span className="sat-label">{SENTIMENT_LABELS[key]}</span>
          <span className="sat-share"><CountNumber value={total ? (counts[i] * 100) / total : 0} format={(v) => `${fmt.decimal(v)}٪`}/></span>
        </div>)}
      </div>
    </div>
  </section>;
}

interface ArticleCard { id: string; slug: string; title: string; summary: string; published_at: string | null }

const faDate = new Intl.DateTimeFormat("fa-IR", { year: "numeric", month: "long", day: "numeric" });

function LatestArticles() {
  const [items, setItems] = useState<ArticleCard[] | null>(null);
  useEffect(() => {
    request<{ items: ArticleCard[] }>("/v1/help/articles?kind=article&limit=3")
      .then((r) => setItems(r.items))
      .catch(() => setItems([]));
  }, []);
  if (!items || items.length === 0) return null;
  return <section className="site-section site-articles" id="articles"><div className="site-container">
    <h2>مقالات و آموزش‌ها</h2>
    <p className="site-intro">راهنمای نصب، نکات تحلیل مکالمات و پاسخ پرسش‌های متداول.</p>
    <div className="site-article-grid">{items.map((a) => <article key={a.id}>
      {a.published_at ? <time dateTime={a.published_at}>{faDate.format(new Date(a.published_at))}</time> : null}
      <h3><Link to={`/help/${a.slug}`}>{a.title}</Link></h3>
      {a.summary ? <p>{a.summary}</p> : null}
      <Link className="site-article-more" to={`/help/${a.slug}`}>ادامهٔ مطلب</Link>
    </article>)}</div>
    <p className="site-pricing-note"><Link to="/help">همهٔ مقالات و آموزش‌ها</Link></p>
  </div></section>;
}

export default function Landing() {
  const [, setParams] = useSearchParams();
  const [menuOpen, setMenuOpen] = useState(false);
  const [plans, setPlans] = useState<PublicPlan[]>([]);
  const [siteContact, setSiteContact] = useState({ phone: "09399093062", trust_html: "" });
  const [plansState, setPlansState] = useState<"loading" | "ready" | "error">("loading");
  function loadPlans() {
    setPlansState("loading");
    request<PublicPlan[]>("/v1/plans").then((items) => { setPlans(items); setPlansState("ready"); }).catch(() => setPlansState("error"));
  }
  useEffect(loadPlans, []);
  useEffect(() => {
    request<{ phone: string; trust_html: string }>("/v1/site/contact-settings")
      .then(setSiteContact)
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuOpen]);
  function openQuickDemo() {
    setParams((current) => { const next = new URLSearchParams(current); next.set("quickDemo", "1"); return next; });
  }
  return <div className="marketing-site" dir="rtl">
    <header className="site-header"><div className="site-container site-nav">
      <a href="#top" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></a>
      <nav id="site-navigation" className={menuOpen ? "site-links is-open" : "site-links"} aria-label="منوی اصلی">
        <a href="#features" onClick={() => setMenuOpen(false)}>امکانات</a><a href="#usecases" onClick={() => setMenuOpen(false)}>کاربردها</a><a href="#pricing" onClick={() => setMenuOpen(false)}>تعرفه‌ها</a><Link to="/help">مقالات</Link><Link to="/about">درباره ما</Link><Link to="/contact">تماس با ما</Link>
      </nav>
      <div className="site-nav-actions"><Link className="site-button" to="/login">ورود به پنل</Link><button className="site-menu" aria-controls="site-navigation" aria-expanded={menuOpen} aria-label={menuOpen ? "بستن منو" : "باز کردن منو"} onClick={() => setMenuOpen(!menuOpen)}><Icon name={menuOpen ? "x" : "menu"}/></button></div>
    </div></header>
    <main id="top">
      <section className="site-hero" style={{ "--site-hero-art": `url(${heroBackdrop})` } as CSSProperties}><div className="site-container site-split">
        <div><h1 className="site-hero-title"><span>مشتری‌هایتان در مکالمات حرف می‌زنند؛</span><span className="site-hero-title-accent">شما می‌شنوید؟<svg className="site-hero-wave" viewBox="0 0 300 16" preserveAspectRatio="none" aria-hidden="true" focusable="false"><defs><linearGradient id="site-wave-grad" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stopColor="#c62828" stopOpacity=".25"/><stop offset=".18" stopColor="#c62828"/><stop offset=".82" stopColor="#e2483f"/><stop offset="1" stopColor="#e2483f" stopOpacity=".25"/></linearGradient></defs><path className="site-wave-main" pathLength="1" d="M298 9C264 2 236 15 202 8S140 2 106 8 48 15 2 5"/></svg></span></h1><p>هر روز، فرصت‌های فروش و نشانه‌های نارضایتی در مکالمات پنهان می‌مانند. صداسنج آن‌ها را به اقدام روشن برای بهبود تجربه مشتری و عملکرد تیم تبدیل می‌کند.</p><div className="site-actions"><button className="site-button" type="button" onClick={openQuickDemo}>تست رایگان</button><a className="site-button site-button-outline" href="#features">مشاهده امکانات</a></div></div>
      </div></section>
      <section className="site-section" id="features"><div className="site-container"><h2>همه‌چیز برای درک بهتر تماس‌ها</h2><div className="site-benefits">{benefits.map((item) => <article key={item.title}><Icon name={item.icon} size={32}/><h3>{item.title}</h3><p>{item.body}</p></article>)}</div></div></section>
      <section className="site-awareness" id="awareness"><div className="site-container site-awareness-grid">
        <div>
          <h2>وقتی بدانند شنیده می‌شوند، <span className="site-awareness-hl">بهتر کار می‌کنند</span></h2>
          <p>در پژوهشی، وقتی عملکرد کارکنان پایش شد، فروش حدود <mark>۷ درصد</mark> بالاتر رفت.</p>
          <small>Management Science، ۲۰۱۵؛ بررسی ۳۹۲ رستوران · <a href="https://econpapers.repec.org/RePEc:inm:ormnsc:v:61:y:2015:i:10:p:2299-2319" target="_blank" rel="noopener noreferrer">منبع پژوهش</a></small>
        </div>
        <img src={awarenessArt} alt="هدست در مرکز موج‌های صدا و نتیجه‌ی بررسی مکالمات" loading="lazy" width="794" height="749"/>
      </div></section>
      <section className="site-section" id="workflow">
        <div className="site-container">
          <h2>از مکالمه تا اقدام همه زیر ذره‌بین</h2>
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
      <UseCases/>
      <SatisfactionShowcase/>
      <section className="site-integration-banner" aria-label="اتصال سامانه تلفنی به صداسنج"><picture><source media="(max-width: 760px)" srcSet={integrationBannerMobile}/><img src={integrationBanner} alt="اتصال Issabel و FreePBX به داشبورد تحلیل مکالمات صداسنج" loading="lazy" decoding="async"/></picture><div className="site-integration-copy"><h2>به‌راحتی به تلفن ابری شما متصل می‌شود</h2><p>صداسنج با ماژول حرفه‌ای روی FreePBX و Issabel نصب می‌شود و همهٔ فرایندها به‌صورت خودکار انجام می‌شوند.</p><a className="site-button" href="https://github.com/aminazadi/Sedasanj-Module.git" target="_blank" rel="noreferrer">دانلود ماژول</a></div></section>
      <section className="site-section site-security" id="security"><div className="site-container"><h2>امنیت در تمام مراحل</h2><div className="site-benefits">{([{ icon: "shield", title: "حریم خصوصی", body: "داده‌ها و اطلاعات تماس هر سازمان در پایگاه داده‌ای مستقل نگهداری می‌شوند تا مرز روشنی میان اطلاعات سازمان‌ها برقرار باشد." }, { icon: "lock", title: "کنترل دسترسی", body: "برای هر کاربر نقش و سطح دسترسی مشخصی تعریف می‌شود تا اعضای تیم فقط به بخش‌ها و اطلاعات مرتبط با مسئولیت خود دسترسی داشته باشند." }, { icon: "layers", title: "استقرار منعطف", body: "سامانه می‌تواند روی سرورهای اختصاصی سازمان شما نصب و اجرا شود؛ در این حالت زیرساخت و داده‌ها در محیط تحت مدیریت خودتان باقی می‌مانند." }] as typeof benefits).map((item) => <article key={item.title}><Icon name={item.icon} size={28}/><h3>{item.title}</h3><p>{item.body}</p></article>)}</div></div></section>
      <section className="site-section" id="pricing"><div className="site-container"><h2>پلن‌های مقرون بصرفه</h2><p className="site-intro">قابلیت‌های اصلی مشترک؛ ظرفیت متناسب با نیاز تیم شما. اشتراک‌ها سالانه هستند.</p>
        {plansState === "loading" && <p className="site-status" role="status">در حال دریافت پلن‌ها…</p>}
        {plansState === "error" && <div className="site-status" role="alert"><p>دریافت پلن‌ها انجام نشد.</p><button className="site-button site-button-outline" onClick={loadPlans}>تلاش دوباره</button></div>}
        {plansState === "ready" && !plans.length && <p className="site-status">در حال حاضر پلنی برای نمایش وجود ندارد.</p>}
        <div className="site-plans">{plans.map((plan) => { const demo = plan.code === "demo"; const price = plan.annual_price_toman; const extra = plan.extra_operator_annual_toman; return <article className={`site-plan${plan.code === "silver" ? " site-plan-featured" : ""}`} key={plan.code}><PlanArtwork code={plan.code} name={plan.name}/><h3>{plan.name}</h3><div className="site-price"><AnimatedPrice value={demo ? null : price} formatted={demo ? "رایگان" : price == null ? "تماس بگیرید" : fmt.int(price)}/>{!demo && price != null && <span>تومان / سال</span>}</div><ul><li>{fmt.int(plan.base_operators)} کاربر اپراتور</li><li>{fmt.int(plan.assistant_monthly_messages)} پیام دستیار در ماه</li><li>{fmt.int(plan.intro_minutes)} دقیقه رایگان در ماه</li><li>هر دقیقه اضافه {fmt.toman(plan.overage_price_per_minute_toman)}</li>{plan.allows_extra_operators && extra != null && <li>اپراتور اضافه: {fmt.toman(extra)} / سال</li>}</ul><Link className={`site-button${plan.code === "silver" ? "" : " site-button-outline"}`} to={`/signup?plan=${encodeURIComponent(plan.code)}`}>شروع با پلن {plan.name}</Link></article>; })}</div>
        <p className="site-pricing-note">نصب اولیه رایگان است. برای استقرار اختصاصی <Link to="/contact">با ما تماس بگیرید.</Link></p>
      </div></section>
      <LatestArticles/>
      <QuickDemoEntry />
    </main>
    <WhyVideoButton/>
    <footer className="site-footer">
      <section className="site-footer-contact" aria-labelledby="site-footer-contact-title">
        <div className="site-container site-footer-contact-inner">
          <div><h2 id="site-footer-contact-title">با ما تماس بگیرید</h2><p>پذیرای صدای گرم شما خواهیم بود</p></div>
          <a className="site-footer-phone" href={`tel:${siteContact.phone}`} dir="rtl">{siteContact.phone.replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)])}</a>
        </div>
      </section>
      <div className="site-container site-footer-main">
        <div className="site-footer-brand"><strong>درباره صداسنج</strong><Link to="/" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></Link><p>سامانه هوشمند تحلیل مکالمات فارسی</p></div>
        <nav className="site-footer-links" aria-label="لینک‌های پرکاربرد"><strong>لینک‌های پرکاربرد</strong><Link to="/#features">امکانات</Link><Link to="/#pricing">پلن‌ها</Link><Link to="/about">درباره ما</Link><Link to="/contact">تماس با ما</Link><Link to="/login">ورود به پنل</Link></nav>
        <nav className="site-footer-legal" aria-label="قوانین و حریم خصوصی"><Link to="/terms">قوانین استفاده</Link><Link to="/privacy">حریم خصوصی</Link><Link to="/cancellation">لغو اشتراک</Link></nav>
        <div className="site-footer-trust" aria-label="نمادهای اعتماد"><strong>نمادهای اعتماد</strong>{siteContact.trust_html ? <iframe className="site-footer-trust-frame" title="نمادهای اعتماد صداسنج" sandbox="allow-scripts" srcDoc={siteContact.trust_html}/> : <div className="site-footer-trust-slots"><span aria-hidden="true">جایگاه نماد</span><span aria-hidden="true">جایگاه نماد</span></div>}</div>
      </div>
      <div className="site-container site-footer-bottom"><small>© ۱۴۰۵ صداسنج</small></div>
    </footer>
  </div>;
}
