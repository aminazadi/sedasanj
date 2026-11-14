import { useScrollHeader } from "../components/useScrollHeader";
import SiteFooter from "../components/SiteFooter";
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import logo from "../assets/sedasanj-refined-master.webp";
import { srcSetFor } from "../lib/imageSources";
import heroBackdrop from "../assets/hero-office.webp";
import integrationBanner from "../assets/telephony-integration-banner-desktop.webp";
import integrationBannerMobile from "../assets/telephony-integration-banner-mobile.webp";
import awarenessArt from "../assets/operator-awareness.svg";
import ucGov from "../assets/usecases/gov.webp";
import ucFinance from "../assets/usecases/finance.webp";
import ucHealth from "../assets/usecases/health.webp";
import ucSales from "../assets/usecases/sales.webp";
import ucSupport from "../assets/usecases/support.webp";
import ucCommerce from "../assets/usecases/commerce.webp";
import planDemoImage from "../assets/plan-demo.webp";
import planBronzeImage from "../assets/plan-bronze.webp";
import planSilverImage from "../assets/plan-silver.webp";
import planGoldImage from "../assets/plan-gold.webp";
import "./Landing.css";
import { fmt, request, SENTIMENT_LABELS } from "../api";
import type { PublicPlan } from "../types";
import QuickDemoEntry from "../components/QuickDemoEntry";
import WhyVideoButton, { WhyVideoDialog, WhyVideoPlay, useWhyVideo } from "../components/WhyVideoButton";
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
  return { x, y, d: `M50 50 Q${mx.toFixed(2)} ${my.toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)}`, r: `M${x.toFixed(2)} ${y.toFixed(2)} Q${mx.toFixed(2)} ${my.toFixed(2)} 50 50` };
});

function UseCases() {
  const [active, setActive] = useState(0);
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const current = useCases[active];
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  pausedRef.current = paused;
  const [typedCount, setTypedCount] = useState(0);
  const [autoplay] = useState(() => typeof window === "undefined" || !window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const activeTotal = useCases[active].title.length + useCases[active].body.length;
  useEffect(() => {
    if (!autoplay) { setTypedCount(Number.MAX_SAFE_INTEGER); return; }
    setTypedCount(0);
    const timer = window.setInterval(() => {
      if (pausedRef.current) return;
      setTypedCount((n) => {
        if (n >= activeTotal) { window.clearInterval(timer); return n; }
        return n + 2;
      });
    }, 30);
    return () => window.clearInterval(timer);
  }, [active, autoplay, activeTotal]);
  const typed = typedCount >= activeTotal;
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
      <h2>چرا به صداسنج نیاز دارید؟</h2>
      <div className="uc-stage" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
        <div className="uc-orbit" role="tablist" aria-label="حوزه‌های کاربرد صداسنج" aria-orientation="vertical">
          <svg className="uc-branches" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
            {ucNodes.map((n, i) => <path key={useCases[i].id} d={n.d} pathLength={1} className="uc-branch"/>)}
            <path key={`on-${current.id}`} d={ucNodes[active].d} pathLength={1} className="uc-branch uc-branch-on"/>
            <g key={`flow-${current.id}`} className="uc-flow" aria-hidden="true">
              {[0, 1, 2, 3, 4].flatMap((k) => [
                <circle key={`o-${k}`} r={0.9 + (k % 3) * 0.35} className="uc-flow-dot" opacity="0">
                  <animateMotion dur="2.6s" begin={`${(k * 0.52).toFixed(2)}s`} repeatCount="indefinite" path={ucNodes[active].d} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines=".45 0 .55 1"/>
                  <animate attributeName="opacity" values="0;.9;.9;0" keyTimes="0;.2;.8;1" dur="2.6s" begin={`${(k * 0.52).toFixed(2)}s`} repeatCount="indefinite"/>
                </circle>,
                <circle key={`i-${k}`} r={0.9 + ((k + 1) % 3) * 0.35} className="uc-flow-dot uc-flow-back" opacity="0">
                  <animateMotion dur="2.9s" begin={`${(k * 0.58 + 0.3).toFixed(2)}s`} repeatCount="indefinite" path={ucNodes[active].r} keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines=".45 0 .55 1"/>
                  <animate attributeName="opacity" values="0;.9;.9;0" keyTimes="0;.2;.8;1" dur="2.9s" begin={`${(k * 0.58 + 0.3).toFixed(2)}s`} repeatCount="indefinite"/>
                </circle>,
              ])}
            </g>
          </svg>
          <div className="uc-core" aria-hidden="true"><span className="uc-ring"/><span className="uc-ring uc-ring-late"/><svg className="uc-pulse" viewBox="0 0 24 24" width="30" height="30" fill="none" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path className="uc-pulse-base" d="M2 12h5l2-7 4 14 2-7h7" pathLength={1}/><path className="uc-pulse-beat" d="M2 12h5l2-7 4 14 2-7h7" pathLength={1}/></svg><span className="uc-core-label">صداسنج</span></div>
          {useCases.map((item, index) => <button key={item.id} ref={(el) => { refs.current[index] = el; }} type="button" role="tab" id={`usecase-tab-${item.id}`} aria-selected={index === active} aria-controls="usecase-panel" tabIndex={index === active ? 0 : -1} className={`uc-node${ucNodes[index].y < 45 ? " is-above" : ""}${index === active ? " is-active" : ""}`} style={{ left: `${ucNodes[index].x}%`, top: `${ucNodes[index].y}%` }} onClick={() => setActive(index)} onMouseEnter={() => setActive(index)} onKeyDown={(event) => onKey(event, index)}>
            <span className="uc-node-dot"><img src={ucPhotos[item.id].src} alt={ucPhotos[item.id].alt} width={120} height={120} loading="lazy" decoding="async"/>{autoplay && typed && index === active ? <svg className={`uc-node-progress${paused ? " is-paused" : ""}`} viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><rect x="0" y="0" width="100" height="100" pathLength={1} onAnimationEnd={() => setActive((v) => (v + 1) % useCases.length)}/></svg> : null}</span><span className="uc-node-label">{ucShortLabels[item.id] ?? item.label}</span>
          </button>)}
        </div>
        <div className="uc-bubble" role="tabpanel" id="usecase-panel" aria-labelledby={`usecase-tab-${current.id}`}>
          {useCases.map((item, index) => {
            const on = index === active;
            return <div key={item.id} className={`uc-panel${on ? " is-on" : ""}`} aria-hidden={!on} {...(on ? {} : { inert: "" as unknown as boolean })}>
              {on && autoplay && !typed ? <>
                <h3 aria-label={item.title}><span aria-hidden="true">{item.title.slice(0, typedCount)}{typedCount < item.title.length ? <i className="uc-caret"/> : null}</span></h3>
                <p aria-label={item.body}><span aria-hidden="true">{item.body.slice(0, Math.max(0, typedCount - item.title.length))}{typedCount >= item.title.length ? <i className="uc-caret"/> : null}</span></p>
              </> : <>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </>}
            </div>;
          })}
        </div>
      </div>
    </div>
  </section>;
}

type AppRelease = { download_path: string };
const appFeatures: Array<{ icon: IconName; title: string; body: string }> = [
  { icon: "headset", title: "ضبط جلسه با یک لمس", body: "جلسه را روی گوشی ضبط کنید؛ متن فارسی هم‌زمان با ضبط ساخته می‌شود." },
  { icon: "users", title: "تفکیک گوینده‌ها", body: "برای افراد حاضر نمونهٔ صدا ثبت کنید تا هر جمله به گوینده‌اش نسبت داده شود." },
  { icon: "refresh", title: "اتصال به صداسنج", body: "با اسکن یک QR به سازمان خود وصل شوید و جلسه‌ها را به پنل بفرستید." },
];
const LIVE_LINES = [
  { speaker: "علی سهرابی", text: "سلام و وقت بخیر، جلسه‌ی امروز را با مرور گزارش فروش هفته‌ی گذشته شروع می‌کنیم." },
  { speaker: "مریم احمدی", text: "فروش نسبت به هفته‌ی قبل حدود ده درصد بالاتر رفته و بیشترین رشد مربوط به شعبه‌ی غرب بوده است." },
  { speaker: "رضا کریمی", text: "ولی تعداد شکایت‌های مربوط به تأخیر در ارسال هم کمی زیاد شده و باید بررسی‌اش کنیم." },
  { speaker: "مریم احمدی", text: "بله، بیشتر این تأخیرها از انبار مرکزی بوده. با مسئول انبار صحبت کرده‌ام و برنامه‌ی تازه‌ای می‌دهند." },
  { speaker: "علی سهرابی", text: "عالیه. پس تا پنجشنبه گزارش کامل را برای همه ارسال کنید تا در جلسه‌ی بعد درباره‌اش تصمیم بگیریم." },
  { speaker: "رضا کریمی", text: "موضوع بعدی بودجه‌ی تبلیغات فصل آینده است؛ پیشنهاد من این است که سهم کانال‌های آنلاین بیشتر شود." },
  { speaker: "مریم احمدی", text: "موافقم، چون هزینه‌ی جذب مشتری در آن کانال‌ها نسبت به سه ماه پیش حدود بیست درصد کمتر شده است." },
  { speaker: "رضا کریمی", text: "باشه، پیگیری‌ها را همین امروز در سامانه ثبت می‌کنم و برای تیم می‌فرستم." },
  { speaker: "علی سهرابی", text: "خیلی خوب، اگر نکتهٔ دیگری نیست جلسه را همین‌جا تمام می‌کنیم. ممنون از همه." },
];
function LiveTyping() {
  const words = LIVE_LINES.map(({ text }) => text.split(" "));
  const [shown, setShown] = useState<number[]>(() => (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches ? words.map((w) => w.length) : [0]));
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const timer = window.setTimeout(() => {
      const line = shown.length - 1;
      if (shown[line] < words[line].length) setShown([...shown.slice(0, line), shown[line] + 1]);
      else if (line < words.length - 1) setShown([...shown, 0]);
      else setShown([0]);
    }, shown[shown.length - 1] >= words[shown.length - 1].length ? (shown.length === words.length ? 4000 : 650) : 110);
    return () => window.clearTimeout(timer);
  }, [shown]);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    if (shown.length === 1 && shown[0] === 0) { el.scrollTop = 0; stick.current = true; return; }
    if (stick.current) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [shown]);
  return <div className="rec-lines" ref={box} onScroll={(event) => { const el = event.currentTarget; stick.current = el.scrollTop >= el.scrollHeight - el.clientHeight - 48; }}>{shown.map((count, i) => <p key={i}><strong>{LIVE_LINES[i].speaker}:</strong>{" "}{words[i].slice(0, count).join(" ")}{i === shown.length - 1 && count < words[i].length && <span className="rec-caret"/>}</p>)}</div>;
}

const ucShortLabels: Record<string, string> = {
  gov: "دولتی",
  finance: "بانک و بیمه",
  health: "درمان",
  sales: "فروش",
  support: "پشتیبانی",
  commerce: "فروشگاه آنلاین",
};

function RecClock() {
  const [sec, setSec] = useState(167);
  useEffect(() => {
    const id = window.setInterval(() => setSec((v) => v + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  const mm = String(Math.floor(sec / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  return <span dir="ltr">{mm}:{ss}</span>;
}

function AppDownload() {
  const [release, setRelease] = useState<AppRelease | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  function load() {
    setState("loading");
    request<{ release: AppRelease | null }>("/v1/jalase-negar/android/latest")
      .then((data) => { setRelease(data.release); setState("ready"); })
      .catch(() => setState("error"));
  }
  useEffect(load, []);
  return <section className="site-hero site-app" id="app"><div className="site-container site-split site-app-grid">
    <div className="site-app-copy">
      <h2 className="site-hero-title site-hero-title-flow">راحت‌تر و هر زمان<br/><span className="site-hero-title-accent">صورت‌جلسه‌ای حرفه‌ای</span> داشته باشید</h2>
      <p className="site-app-pitch">با جلسه‌نگار <strong>جلسه‌های حضوری را ضبط کنید</strong>، <em>متن فارسی</em> گفت‌وگو را دریافت کنید و آن را به <em>پنل سازمان</em> بفرستید.</p>
      <ul className="site-app-features">{appFeatures.map((item) => <li key={item.title}><Icon name={item.icon} size={18}/><span>{item.title}</span></li>)}</ul>
      <div className="site-actions">
        {state === "ready" && release && <a className="site-button" href={release.download_path} download><Icon name="download" size={18}/>دانلود جلسه‌نگار</a>}
        {state === "loading" && <button className="site-button" type="button" disabled aria-busy="true"><Icon name="download" size={18}/>در حال آماده‌سازی لینک دانلود…</button>}
        {state === "error" && <button className="site-button site-button-outline" type="button" onClick={load}><Icon name="refresh" size={18}/>تلاش دوباره</button>}
        {state === "ready" && !release && <button className="site-button" type="button" disabled><Icon name="download" size={18}/>دانلود به‌زودی در دسترس خواهد بود</button>}
        <Link className="site-button site-button-outline" to="/help/jalase-negar-android-install"><Icon name="layers" size={18}/>راهنمای نصب</Link>
      </div>
    </div>
    <div className="site-app-visual" role="img" aria-label="صفحهٔ ضبط جلسه در اپ جلسه‌نگار؛ متن زنده با نام گوینده‌ها، موج صدا و دکمه‌های توقف موقت و پایان">
      <div className="site-app-phone" aria-hidden="true">
        <svg className="phone-app-icon" viewBox="0 0 192 192" aria-hidden="true"><rect width="192" height="192" rx="44" fill="#4b6e48"/><rect x="85" y="22" width="22" height="148" fill="#fff"/><rect x="54" y="54" width="22" height="84" fill="#b9b48f"/><rect x="116" y="54" width="22" height="84" fill="#b9b48f"/><rect x="24" y="76" width="22" height="40" fill="#b9b48f"/><rect x="146" y="76" width="22" height="40" fill="#b9b48f"/></svg>
        <span className="phone-btn phone-btn-power"/><span className="phone-btn phone-btn-vol"/>
        <div className="site-app-screen">
          <span className="phone-camera"/>
          <div className="phone-status"><span dir="ltr">12:30</span><div><svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor"><path d="M2 20h3V15H2zM7 20h3V11H7zM12 20h3V7h-3zM17 20h3V3h-3z"/></svg><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M2 9a15 15 0 0 1 20 0M5.5 13a10 10 0 0 1 13 0M9 17a5 5 0 0 1 6 0"/></svg><b><i/></b></div></div>
          <div className="rec-bar"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m9 6 6 6-6 6"/></svg><span>ضبط جلسه</span></div>
          <div className="rec-panel">
            <div className="rec-panel-head">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 11h3M13 11h4M7 15h6M16 15h1"/></svg>
              <b>متن زنده</b><i/><span>در حال شنیدن…</span>
            </div>
            <LiveTyping/>
          </div>
          <div className="rec-monitor"><RecClock/><div className="rec-wave">{Array.from({ length: 46 }, (_, i) => <i key={i} style={{ "--h": `${12 + Math.abs(Math.sin(i * 1.7) * 62 + Math.cos(i * 0.6) * 22)}%`, "--d": `${(i % 9) * 90}ms` } as CSSProperties}/>)}</div></div>
          <div className="rec-controls">
            <div><span className="rec-diamond rec-diamond-outline"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z"/></svg></span><small>توقف موقت</small></div>
            <div><span className="rec-diamond rec-diamond-stop"><svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M6 6h12v12H6z"/></svg></span><small>پایان و ذخیره</small></div>
          </div>
          <span className="phone-home"/>
        </div>
      </div>
    </div>
  </div></section>;
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
      <h2>حال مشتری‌هایتان را در یک نگاه ببینید</h2>
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
    <div className="site-article-grid">{items.map((a) => <article key={a.id}>
      {a.published_at ? <time dateTime={a.published_at}>{faDate.format(new Date(a.published_at))}</time> : null}
      <h3><Link to={`/help/${a.slug}`}>{a.title}</Link></h3>
      {a.summary ? <p>{a.summary}</p> : null}
      <Link className="site-article-more" to={`/help/${a.slug}`}>ادامهٔ مطلب<Icon name="arrow" size={18}/></Link>
    </article>)}</div>
    <p className="site-pricing-note"><Link to="/help">همهٔ مقالات و آموزش‌ها</Link></p>
  </div></section>;
}

export default function Landing() {
  const whyVideo = useWhyVideo();
  const heroRef = useRef<HTMLElement>(null);
  const [heroInView, setHeroInView] = useState(true);
  useEffect(() => {
    const node = heroRef.current;
    if (!node || typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver(([entry]) => setHeroInView(entry.isIntersecting), { threshold: 0.4 });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  const [, setParams] = useSearchParams();
  const [menuOpen, setMenuOpen] = useState(false);
  const { headerRef, hidden: headerHidden } = useScrollHeader(menuOpen);
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
  function openQuickDemo() {
    setParams((current) => { const next = new URLSearchParams(current); next.set("quickDemo", "1"); return next; });
  }
  return <div className="marketing-site" dir="rtl">
    <header ref={headerRef} className={`site-header${headerHidden ? " is-hidden" : ""}`}><div className="site-container site-nav">
      <a href="#top" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></a>
      <nav id="site-navigation" className={menuOpen ? "site-links is-open" : "site-links"} aria-label="منوی اصلی">
        <a href="#features" onClick={() => setMenuOpen(false)}><Icon name="layers" size={16}/><span>امکانات</span></a><a href="#usecases" onClick={() => setMenuOpen(false)}><Icon name="target" size={16}/><span>کاربردها</span></a><a href="#app" onClick={() => setMenuOpen(false)}><Icon name="download" size={16}/><span>اپلیکیشن</span></a><a href="#pricing" onClick={() => setMenuOpen(false)}><Icon name="chart" size={16}/><span>تعرفه‌ها</span></a><Link to="/help"><Icon name="tasks" size={16}/><span>مقالات</span></Link><Link to="/about"><Icon name="users" size={16}/><span>درباره ما</span></Link><Link to="/contact"><Icon name="phone" size={16}/><span>تماس با ما</span></Link>
      </nav>
      <div className="site-nav-actions"><Link className="site-login-button" to="/login"><span>ورود به پنل</span><Icon name="arrow" size={16} className="site-login-arrow"/></Link><button className="site-menu" aria-controls="site-navigation" aria-expanded={menuOpen} aria-label={menuOpen ? "بستن منو" : "باز کردن منو"} onClick={() => setMenuOpen(!menuOpen)}><Icon name={menuOpen ? "x" : "menu"}/></button></div>
    </div></header>
    <main id="top">
      <section className="site-hero" ref={heroRef}><img className="site-hero-backdrop" src={heroBackdrop} srcSet={srcSetFor(heroBackdrop)} sizes="max(100vw, 160svh)" alt="" aria-hidden="true" width={1774} height={887} fetchPriority="high" decoding="async"/><div className="site-container site-split">
        <div><h1 className="site-hero-title site-hero-title-flow">هر آنچه از <span className="site-hero-title-accent">پردازش صوت</span> در سازمانتان نیاز دارید</h1><p>هر مکالمه به متن، خلاصه و تحلیل تبدیل می‌شود؛ بدون اینکه کسی ساعت‌ها فایل صوتی گوش کند.</p><div className="site-actions"><button className="site-button site-hero-demo" type="button" onClick={openQuickDemo}><svg className="hero-demo-border" aria-hidden="true" focusable="false"><rect className="hero-demo-border-track" pathLength="100"/><rect className="hero-demo-border-trail" pathLength="100"/></svg><span>تست صداسنج در کمتر از ۶۰ ثانیه</span></button><a className="site-hero-features-link" href="#features"><span>مشاهده امکانات</span><Icon name="arrowDown" size={18}/></a></div></div>
        <div className="site-hero-play"><WhyVideoPlay video={whyVideo}/></div>
      </div>
        <button className="site-scroll-down" type="button" aria-label="رفتن به بخش بعدی" onClick={() => document.getElementById("features")?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" })}><span className="site-scroll-text" dir="ltr">Scroll Down</span><span className="site-scroll-icon" aria-hidden="true"/></button>
      </section>
      <section className="site-section" id="features"><div className="site-container"><h2>همه‌چیز برای درک بهتر تماس‌ها</h2><div className="site-benefits">{benefits.map((item) => <article key={item.title}><Icon name={item.icon} size={32}/><h3>{item.title}</h3><p>{item.body}</p></article>)}</div></div></section>
      <section className="site-awareness" id="awareness">
        <svg className="awareness-launch-edge" viewBox="0 0 1440 180" preserveAspectRatio="xMaxYMin slice" fill="none" aria-hidden="true" focusable="false">
          <path fill="var(--site-canvas)" d="M0 0H1440V68C1360 98 1300 54 1236 68C1160 84 1134 136 1040 132C920 126 864 50 732 58C590 66 552 142 408 130C260 118 180 48 0 92Z"/>
          <path stroke="#8fb58a" strokeWidth="2" opacity=".55" d="M0 112C180 68 260 138 408 150C552 162 590 86 732 78C864 70 920 146 1040 152C1134 156 1170 100 1220 88"/>
          <path fill="#cfe0c9" d="M0 80C210 36 266 114 410 112C554 110 600 42 740 44C900 46 948 130 1050 114C1128 102 1168 66 1204 66C1160 90 1148 132 1040 132C920 126 864 50 732 58C590 66 552 142 408 130C260 118 180 48 0 92Z"/>
          <g transform="translate(1204 64) rotate(38)">
            <path fill="#f5c542" d="M-10 29Q-18 53 0 68Q18 53 10 29Z"/>
            <path fill="#fff6cf" d="M-5 30Q-8 46 0 54Q8 46 5 30Z"/>
            <path fill="#8fb58a" stroke="#203b25" strokeWidth="2" strokeLinejoin="round" d="M-15 4L-30 24L-28 43L-12 30M15 4L30 24L28 43L12 30"/>
            <path fill="#f2f0ef" stroke="#203b25" strokeWidth="2.5" d="M0-49C-22-30-24 6-14 31H14C24 6 22-30 0-49Z"/>
            <path fill="#8fb58a" d="M0-47C-9-39-14-30-17-20H17C14-30 9-39 0-47Z"/>
            <circle cy="-3" r="10" fill="#2f4a2d" stroke="#f5c542" strokeWidth="3"/>
            <path stroke="#fff" strokeWidth="2" strokeLinecap="round" d="M-4-6L0-10"/>
            <path stroke="#203b25" strokeWidth="2.5" d="M-13 24H13"/>
          </g>
          <path stroke="#b2ac88" strokeWidth="2" strokeLinecap="round" d="M1300 24V36M1294 30H1306M1124 38V46M1120 42H1128"/>
        </svg>
        <div className="site-container site-awareness-grid">
        <div>
          <h2>وقتی بدانند شنیده می‌شوند، <span className="site-awareness-hl">بهتر عمل می‌کنند</span></h2>
          <p>در پژوهشی، وقتی عملکرد کارکنان پایش شد، فروش حدود <mark>۷ درصد</mark> بالاتر رفت.</p>
        </div>
        <img src={awarenessArt} alt="هدست در مرکز موج‌های صدا و نتیجه‌ی بررسی مکالمات" loading="lazy" width="794" height="749"/>
      </div>
        <svg className="awareness-bottom-edge" viewBox="0 0 1440 180" preserveAspectRatio="none" fill="none" aria-hidden="true" focusable="false">
          <g transform="translate(1440 180) rotate(180)">
            <path fill="var(--site-canvas)" d="M0 0H1440V68C1360 98 1300 54 1236 68C1160 84 1134 136 1040 132C920 126 864 50 732 58C590 66 552 142 408 130C260 118 180 48 0 92Z"/>
            <path stroke="#8fb58a" strokeWidth="2" opacity=".55" d="M0 112C180 68 260 138 408 150C552 162 590 86 732 78C864 70 920 146 1040 152C1134 156 1170 100 1220 88"/>
            <path fill="#cfe0c9" d="M0 80C210 36 266 114 410 112C554 110 600 42 740 44C900 46 948 130 1050 114C1128 102 1168 66 1204 66C1160 90 1148 132 1040 132C920 126 864 50 732 58C590 66 552 142 408 130C260 118 180 48 0 92Z"/>
          </g>
        </svg>
      </section>
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
      <section className="site-integration-banner" aria-label="اتصال سامانه تلفنی به صداسنج"><picture><source media="(max-width: 760px)" srcSet={srcSetFor(integrationBannerMobile) || integrationBannerMobile} sizes="100vw"/><img src={integrationBanner} srcSet={srcSetFor(integrationBanner)} sizes="(max-width: 1160px) 100vw, 1160px" width={1600} height={536} alt="اتصال Issabel و FreePBX به داشبورد تحلیل مکالمات صداسنج" loading="lazy" decoding="async"/></picture><div className="site-integration-copy"><h2>به‌راحتی به تلفن ابری شما متصل می‌شود</h2><p>صداسنج با ماژول حرفه‌ای روی FreePBX و Issabel نصب می‌شود و همهٔ فرایندها به‌صورت خودکار انجام می‌شوند.</p><a className="site-button" href="https://github.com/aminazadi/Sedasanj-Module.git" target="_blank" rel="noreferrer"><Icon name="download" size={18}/>دانلود ماژول</a></div></section>
      <section className="site-section site-security" id="security"><div className="site-container"><h2>امنیت در تمام مراحل</h2><div className="site-benefits">{([{ icon: "shield", title: "حریم خصوصی", body: "داده‌ها و اطلاعات تماس هر سازمان در پایگاه داده‌ای مستقل نگهداری می‌شوند تا مرز روشنی میان اطلاعات سازمان‌ها برقرار باشد." }, { icon: "lock", title: "کنترل دسترسی", body: "برای هر کاربر نقش و سطح دسترسی مشخصی تعریف می‌شود تا اعضای تیم فقط به بخش‌ها و اطلاعات مرتبط با مسئولیت خود دسترسی داشته باشند." }, { icon: "layers", title: "استقرار منعطف", body: "سامانه می‌تواند روی سرورهای اختصاصی سازمان شما نصب و اجرا شود؛ در این حالت زیرساخت و داده‌ها در محیط تحت مدیریت خودتان باقی می‌مانند." }] as typeof benefits).map((item) => <article key={item.title}><Icon name={item.icon} size={28}/><h3>{item.title}</h3><p>{item.body}</p></article>)}</div></div></section>
      <AppDownload/>
      <section className="site-section" id="pricing"><div className="site-container"><h2>پلن‌های مقرون بصرفه</h2>        {plansState === "loading" && <p className="site-status" role="status">در حال دریافت پلن‌ها…</p>}
        {plansState === "error" && <div className="site-status" role="alert"><p>دریافت پلن‌ها انجام نشد.</p><button className="site-button site-button-outline" onClick={loadPlans}><Icon name="refresh" size={18}/>تلاش دوباره</button></div>}
        {plansState === "ready" && !plans.length && <p className="site-status">در حال حاضر پلنی برای نمایش وجود ندارد.</p>}
        <div className="site-plans">{plans.map((plan) => {
          const trial = plan.is_trial;
          const price = plan.annual_price_toman;
          const extra = plan.extra_operator_annual_toman;
          const buyable = trial || price != null;
          return <article className={`site-plan${plan.featured ? " site-plan-featured" : ""}${trial ? " site-plan-trial" : ""}`} key={plan.code}>
            <div className="site-plan-badge-row">{plan.featured ? <span className="site-plan-badge"><Icon name="spark" size={14}/>پیشنهاد صداسنج</span> : trial ? <span className="site-plan-badge site-plan-badge-trial">فرصتی برای آشنایی</span> : null}</div>
            <PlanArtwork code={plan.code} name={plan.name}/>
            <h3>{plan.name}</h3>
            <div className="site-price">
              <AnimatedPrice value={trial ? null : price} formatted={trial ? (plan.trial_days ? `${fmt.int(plan.trial_days)} روز رایگان` : "رایگان") : price == null ? "تماس بگیرید" : fmt.int(price)}/>
              {!trial && price != null && <span>تومان <span className="site-price-period">/ سال</span></span>}
              {trial && <span className="site-trial-caption">صداسنج را در عمل تجربه کنید</span>}
            </div>
            <ul>
              <li><Icon name="check" size={15}/><span><b>{fmt.int(plan.base_operators)}</b> کاربر اپراتور</span></li>
              <li><Icon name="check" size={15}/><span><b>{fmt.int(plan.assistant_monthly_messages)}</b> پیام دستیار در ماه</span></li>
              <li><Icon name="check" size={15}/><span><b>{fmt.int(plan.monthly_included_minutes)}</b> دقیقه رایگان {trial ? "در دوره آزمایشی" : "در ماه"}</span></li>
              <li><Icon name="check" size={15}/><span>هر دقیقه اضافه <b>{fmt.toman(plan.overage_price_per_minute_toman)}</b></span></li>
              {plan.allows_extra_operators && extra != null && <li><Icon name="check" size={15}/><span>اپراتور اضافه: <b>{fmt.toman(extra)}</b> / سال</span></li>}
            </ul>
            <div className="site-plan-action">{buyable ? <Link className={`site-button${plan.featured ? "" : " site-button-outline"}`} to={`/signup?plan=${encodeURIComponent(plan.code)}`}>
              {trial ? "شروع آزمایش رایگان" : `انتخاب پلن ${plan.name}`}<Icon name="arrow" size={18}/>
            </Link> : <Link className="site-button site-button-outline" to="/contact">تماس با فروش<Icon name="arrow" size={18}/></Link>}</div>
          </article>;
        })}</div>
        <p className="site-pricing-note">نصب اولیه رایگان است. برای استقرار اختصاصی <Link to="/contact">با ما تماس بگیرید.</Link></p>
      </div></section>
      <LatestArticles/>
      <QuickDemoEntry />
    </main>
    <WhyVideoButton video={whyVideo} hidden={heroInView}/>
    <WhyVideoDialog video={whyVideo}/>
    <SiteFooter />
  </div>;
}
