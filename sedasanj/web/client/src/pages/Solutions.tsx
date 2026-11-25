import { Link } from "react-router-dom";
import PublicPageFrame from "../components/PublicPageFrame";
import { Icon, type IconName } from "../components/SiteIcon";
import "./Solutions.css";

type Card = { icon: IconName; title: string; text: string };
type Capability = Card & { points: string[] };
type RoadmapItem = Card & { note: string };

const PRODUCTS = [
  {
    icon: "headset" as IconName,
    title: "تحلیل هوشمند تماس‌های تلفنی",
    text: "ماژول اختصاصی صداسنج روی زیرساخت‌های مبتنی بر Asterisk، FreePBX و Issabel نصب می‌شود و مکالمات را برای پردازش به سامانه ارسال می‌کند.",
    points: [
      "متن پردازش‌شده، خلاصه، موضوع و هدف مکالمه",
      "تحلیل احساسات مشتری و روند تغییر آن تا پایان تماس",
      "امتیاز کیفیت پاسخ‌گویی بر اساس معیارهای سازمان",
      "آمار تماس‌های پاسخ‌داده‌شده و بی‌پاسخ",
      "شنیدن صدای اصلی مکالمه در کنار خروجی تحلیل",
    ],
  },
  {
    icon: "tasks" as IconName,
    title: "جلسه‌نگار هوشمند",
    text: "اپلیکیشن موبایل و دسکتاپ که مستقل هم قابل استفاده است و خروجی جلسات را در داشبورد سازمان در دسترس قرار می‌دهد.",
    points: [
      "تبدیل صوت فارسی به متن و اصلاح انسجام متن",
      "تفکیک گویندگان و شناسایی افراد با پروفایل صوتی",
      "خلاصه مذاکرات و استخراج موضوعات و تصمیمات",
      "تولید صورت‌جلسه رسمی مطابق قالب سازمان",
      "بازیابی اطلاعات جلسات با دستیار، در محدوده مجوز کاربر",
    ],
  },
];

const FLOW = [
  { title: "ثبت و ضبط", text: "تماس‌های تلفنی، پیام‌های صوتی و جلسات ثبت‌شده" },
  { title: "پردازش صوت", text: "بهبود وضوح، تبدیل گفتار به متن و تحلیل محتوا" },
  { title: "گزارش و دانش", text: "گزارش‌های مدیریتی، شاخص‌ها و گراف دانش سازمان" },
  { title: "تصمیم و آموزش", text: "پاسخ به پرسش‌های مدیریتی و آموزش کارکنان" },
];

const ROLES: Card[] = [
  { icon: "target", title: "مدیرعامل و هیئت‌مدیره", text: "تصویری واقعی‌تر از آنچه در سازمان می‌گذرد، بدون خواندن گزارش‌های پراکنده." },
  { icon: "headset", title: "مدیران فروش و خدمات مشتریان", text: "موضوعات پرتکرار مشتریان، کیفیت پاسخ‌گویی و فرصت‌های از دست رفته." },
  { icon: "tasks", title: "مدیران عملیات و منابع انسانی", text: "روند عملکرد تیم و اولویت آموزش بر پایه مکالمات واقعی." },
  { icon: "users", title: "دبیرخانه جلسات", text: "صورت‌جلسه رسمی و حفظ تصمیم‌ها پس از پایان جلسه." },
  { icon: "shield", title: "واحد فناوری اطلاعات", text: "استقرار ابری یا داخلی، کنترل دسترسی و نگهداری داده مطابق سیاست سازمان." },
];

const CAPABILITIES: Capability[] = [
  {
    icon: "message",
    title: "صندوق پیام صوتی هوشمند",
    text: "در تماس‌های یک‌طرفه، تماس‌گیرنده بدون حضور اپراتور پیام خود را ثبت می‌کند.",
    points: [
      "تبدیل پیام صوتی به متن و استخراج نکات مهم",
      "دریافت شکایات، پیشنهادات و بازخورد اعضا",
      "خواندن پیام‌های خارج از ساعات کاری بدون شنیدن تک‌تک آن‌ها",
    ],
  },
  {
    icon: "target",
    title: "ارزیابی و مربی هوشمند اپراتورها",
    text: "معیارهای اختصاصی سازمان تعریف می‌شود و هر مکالمه پس از پایان بر همان پایه بررسی می‌شود.",
    points: [
      "معیارهایی مانند احترام، همدلی، رعایت دستورالعمل و کیفیت مذاکره",
      "نکات قابل بهبود و توصیه آموزشی شخصی برای هر اپراتور، با مثال از همان مکالمه",
      "بررسی روند عملکرد تیم و تعیین اولویت آموزش",
    ],
  },
  {
    icon: "brain",
    title: "دستیار هوش مصنوعی سازمان",
    text: "پرسش مدیریتی با زبان طبیعی مطرح می‌شود و پاسخ بر پایه اطلاعات مجاز تماس‌ها و جلسات ارائه می‌گردد.",
    points: [
      "«امروز کدام تماس‌ها بی‌پاسخ مانده‌اند؟»",
      "«در ماه گذشته مشتریان بیشتر از چه موضوعاتی ناراضی بوده‌اند؟»",
      "«درباره یک موضوع مشخص در جلسات چه تصمیمی گرفته شده است؟»",
    ],
  },
  {
    icon: "clock",
    title: "گزارش‌های زمان‌بندی‌شده",
    text: "رفتار دستیار و قالب گزارش قابل تعیین است؛ مثلاً «چه خبر؟» به گزارشی با شاخص‌ها و نمودار تبدیل می‌شود.",
    points: [
      "تعیین زمان تهیه گزارش‌های دوره‌ای، مانند گزارش روزانه ساعت پنج عصر",
      "درخواست گزارش با تماس تلفنی از شماره از پیش تعریف‌شده و بیان آن به‌صورت پیام صوتی",
      "آماده‌شدن گزارش در داشبورد مدیر",
    ],
  },
  {
    icon: "users",
    title: "میکروجلسات سازمانی",
    text: "بسیاری از هماهنگی‌ها و تصمیم‌های مهم در مکالمات کوتاه میان همکاران و مدیران اتفاق می‌افتد، نه فقط در جلسات رسمی.",
    points: [
      "تحلیل مکالمات داخلی ثبت‌شده و مجاز",
      "بازیابی این اطلاعات در کنار جلسات رسمی و تماس‌های خارجی",
      "کاهش وابستگی تصمیم‌گیری به حافظه افراد",
    ],
  },
  {
    icon: "layers",
    title: "دانش اختصاصی و گراف دانش",
    text: "دستیار از مستندات سازمانی مانند Word، Excel، PDF و فایل‌های متنی و همچنین از جلسات و مکالمات، دانش می‌سازد.",
    points: [
      "اتصال افراد، نقش‌ها، ارتباطات، محصولات و مشتریان به یکدیگر",
      "تفسیر اصطلاحات و اشخاص در بستر همان سازمان",
      "اطلاعات استنباط‌شده ممکن است نیازمند بررسی انسانی باشد",
    ],
  },
  {
    icon: "spark",
    title: "کشف اطلاعات مهم",
    text: "دستیار در گزارش‌های خود اطلاعاتی را که با ارزش‌ها و سیاست‌های سازمان مرتبط‌اند برجسته می‌کند، حتی اگر مدیر مستقیماً درباره آن‌ها سؤال نکرده باشد.",
    points: [
      "در یک مؤسسه خیریه، اشاره گذرای تماس‌گیرنده به شرایط دشوار شخصی می‌تواند پیشنهاد پیگیری محترمانه را در گزارش بیاورد",
      "اگر نحوه گفت‌وگوی اپراتور با معیارهای سازمان هم‌خوان نباشد، موضوع و اقدام اصلاحی پیشنهاد می‌شود",
      "این سناریوها بازنویسی غیرهویتی از تجربه بهره‌برداری محصول‌اند",
    ],
  },
];

const INDUSTRIES: Card[] = [
  { icon: "chart", title: "فناوری و الکترونیک", text: "شناخت مشکلات پرتکرار فنی، کیفیت پاسخ پشتیبانی و بازخورد محصولات." },
  { icon: "pulse", title: "صنعتی و نیروگاهی", text: "مستندسازی مذاکرات فنی، هماهنگی‌های پروژه و جلسات کارشناسی." },
  { icon: "users", title: "انجمن‌ها و تشکل‌ها", text: "جمع‌بندی دغدغه‌های اعضا، پیگیری موضوعات پرتکرار و صورت‌جلسات کمیته‌ها." },
  { icon: "phone", title: "سازمان‌های خدماتی", text: "تحلیل کیفیت ارتباط با مشتریان و آموزش هدفمند اپراتورها." },
];

const DEPLOY: Card[] = [
  {
    icon: "pulse",
    title: "پردازش صوت فارسی",
    text: "برای صوت نامناسب، وضوح بهبود داده و نویز کاهش می‌یابد؛ سپس مدل زبانی متن را از نظر انسجام بررسی و اصلاح می‌کند.",
  },
  {
    icon: "layers",
    title: "استقرار ابری",
    text: "پردازش روی زیرساخت صداسنج انجام می‌شود؛ بدون نیاز به سخت‌افزار هوش مصنوعی، با امکان تنظیم مدت نگهداری داده و حذف آن.",
  },
  {
    icon: "lock",
    title: "استقرار اختصاصی (On-Premise)",
    text: "کل نرم‌افزار، داشبورد و مدل‌های پردازشی در زیرساخت داخلی نصب می‌شوند؛ بدون نیاز به اینترنت و بدون خروج داده از سازمان.",
  },
];

const ROADMAP: RoadmapItem[] = [
  { icon: "layers", title: "اتصال اختصاصی به CRM و ERP", text: "پس از بررسی API و استانداردهای نرم‌افزار مقصد.", note: "اتصال آماده به این نرم‌افزارها ارائه نشده است." },
  { icon: "pulse", title: "هشدارهای فوری و کانال‌های اعلان", text: "زیرساخت ارزیابی تماس وجود دارد.", note: "هشدار خودکار هنوز پیاده‌سازی نشده است." },
  { icon: "message", title: "زبان‌های غیرفارسی", text: "نیازمند امکان‌سنجی و توسعه است.", note: "تاکنون پیاده‌سازی و آزمون نشده‌اند." },
  { icon: "phone", title: "پاسخ صوتی مستقیم به درخواست تلفنی", text: "تبدیل متن به گفتار، گفت‌وگوی تعاملی و اقدامات فراتر از تهیه گزارش.", note: "پس از بررسی نیاز و الزامات امنیتی." },
];

const MODEL = [
  {
    icon: "chart" as IconName,
    title: "خدمات ابری و اعتبار پردازشی",
    text: "بسته‌های اشتراکی از نظر امکانات پنل و هوش مصنوعی، تعداد اپراتورها و دقیقه پردازش متفاوت‌اند. اعتبار پردازشی اضافه بدون تغییر اجباری بسته قابل خرید است.",
  },
  {
    icon: "tasks" as IconName,
    title: "پلن‌های جلسه‌نگار",
    text: "نسخه رایگان با مدل کوچک محلی روی گوشی، متن با دقت محدود ارائه می‌کند؛ نسخه‌های پولی از پردازش سروری و اصلاح متن بهره می‌برند و نسخه سازمانی صورت‌جلسه مطابق قالب سازمان می‌سازد.",
  },
  {
    icon: "shield" as IconName,
    title: "استقرار اختصاصی و پشتیبانی",
    text: "مشتری سخت‌افزار مناسب حجم صوت را تهیه می‌کند و صداسنج نصب و راه‌اندازی نرم‌افزار و مدل‌ها را انجام می‌دهد. شرایط دوره اولیه و قرارداد پشتیبانی بر اساس توافق تعیین می‌شود.",
  },
];

const STEPS = [
  "نمایش داشبورد، نمونه صوتی مجاز، گزارش‌ها، مربی هوشمند، جلسه‌نگار و دریافت پیام صوتی و درخواست تلفنی گزارش",
  "بررسی اهداف مدیریتی، تعداد کاربران و اپراتورها، حجم تماس و جلسات",
  "بررسی زیرساخت تلفنی، محرمانگی، سیاست نگهداری داده‌ها و نیازهای استقرار",
  "تعیین دامنه خدمات، مدل ابری یا اختصاصی و ارائه پیشنهاد فنی و مالی",
  "پس از توافق، راه‌اندازی، تعریف معیارها و قالب گزارش‌ها و آغاز بهره‌برداری",
];

function CardGrid({ items, className }: { items: Card[]; className: string }) {
  return <div className={className}>{items.map((item) => <article key={item.title}>
    <Icon name={item.icon} size={30}/>
    <h3>{item.title}</h3>
    <p>{item.text}</p>
  </article>)}</div>;
}

export default function Solutions() {
  return <PublicPageFrame>
    <main className="page-main solutions-page">
      <section className="site-hero page-hero solutions-hero"><div className="site-container solutions-hero-grid">
        <div>
          <h1 className="site-hero-title page-title solutions-title">راهکارهای <span className="site-hero-title-accent">سازمانی</span></h1>
          <p className="solutions-lead">تماس‌ها، جلسات و مکالمات کوتاه کاری، بخش بزرگی از تصمیمات سازمان را می‌سازند و معمولاً پراکنده باقی می‌مانند. صداسنج این ارتباطات را به اطلاعات قابل جست‌وجو، گزارش مدیریتی و دانش سازمانی تبدیل می‌کند.</p>
          <div className="site-actions">
            <Link className="site-button" to="/contact">درخواست جلسه معرفی<Icon name="arrow" size={18}/></Link>
            <Link className="site-button site-button-outline" to="/quick-demo">تست رایگان</Link>
          </div>
        </div>
        <aside className="solutions-snapshot" aria-label="اجزای راهکار در یک نگاه">
          <p className="solutions-snapshot-title">در یک نگاه</p>
          <ul>
            <li><Icon name="headset" size={22}/><span>تحلیل هوشمند تماس‌های تلفنی<small>روی Asterisk، FreePBX و Issabel</small></span></li>
            <li><Icon name="tasks" size={22}/><span>جلسه‌نگار هوشمند<small>اپ موبایل و دسکتاپ، صورت‌جلسه رسمی</small></span></li>
            <li><Icon name="brain" size={22}/><span>دستیار هوش مصنوعی<small>پرسش با زبان طبیعی از تماس‌ها و جلسات</small></span></li>
            <li><Icon name="layers" size={22}/><span>گراف دانش سازمان<small>افراد، نقش‌ها، محصولات و مشتریان</small></span></li>
          </ul>
          <p className="solutions-snapshot-note">هر بخش مستقل قابل بهره‌برداری است؛ در استفاده هم‌زمان، همه در یک داشبورد در اختیار کاربران مجاز قرار می‌گیرد.</p>
        </aside>
      </div></section>

      <section className="site-section"><div className="site-container about-story">
        <div>
          <h2>مکالمات سازمان شما، دانشی برای مدیریت بهتر</h2>
        </div>
        <div className="about-story-copy">
          <p>تماس‌های تلفنی، جلسات رسمی و مکالمات کوتاه کاری، بخش بزرگی از ارتباطات و تصمیمات یک سازمان را شکل می‌دهند. این جریان اطلاعات معمولاً به‌صورت پراکنده باقی می‌ماند و حتی در صورت ضبط، تحلیل همه مکالمات با منابع انسانی محدود دشوار است.</p>
          <p>صداسنج راهکاری عملیاتی برای تبدیل این ارتباطات به اطلاعات قابل جست‌وجو، گزارش مدیریتی و دانش سازمانی است. ارزش محوری محصول، کمک به مدیران برای دستیابی به تصویری واقعی‌تر و جامع‌تر از اتفاقات سازمان است.</p>
        </div>
      </div></section>

      <section className="site-section solutions-pair-section"><div className="site-container">
        <h2>دو کاربرد مکمل، یک داشبورد مشترک</h2>
        <p className="solutions-intro">هر بخش به‌صورت مستقل قابل بهره‌برداری است و در صورت استفاده هم‌زمان، اطلاعات آن‌ها در یک داشبورد در اختیار کاربران مجاز قرار می‌گیرد. هر دو بخش در حال حاضر عملیاتی است و مشتریان از آن‌ها استفاده می‌کنند.</p>
        <div className="solutions-pair">{PRODUCTS.map((product) => <article key={product.title}>
          <Icon name={product.icon} size={32}/>
          <h3>{product.title}</h3>
          <p>{product.text}</p>
          <ul>{product.points.map((point) => <li key={point}>{point}</li>)}</ul>
        </article>)}</div>
      </div></section>

      <section className="site-section solutions-flow-section"><div className="site-container">
        <h2>مسیر ارزش‌آفرینی</h2>
        <ol className="solutions-flow">{FLOW.map((step, index) => <li key={step.title}>
          <span className="solutions-flow-num">{index + 1}</span>
          <strong>{step.title}</strong>
          <span>{step.text}</span>
        </li>)}</ol>
      </div></section>

      <section className="site-section solutions-roles-section"><div className="site-container">
        <h2>برای چه کسانی در سازمان</h2>
        <p className="solutions-intro">هر نقش، متناسب با مجوزهای خود، بخشی از تصویر را می‌بیند.</p>
        <CardGrid items={ROLES} className="solutions-roles"/>
      </div></section>

      <section className="site-section solutions-capabilities-section"><div className="site-container">
        <h2>قابلیت‌های راهکار</h2>
        <div className="solutions-capabilities">{CAPABILITIES.map((item) => <article key={item.title}>
          <Icon name={item.icon} size={28}/>
          <h3>{item.title}</h3>
          <p>{item.text}</p>
          <ul>{item.points.map((point) => <li key={point}>{point}</li>)}</ul>
        </article>)}</div>
      </div></section>

      <section className="site-section solutions-industries-section"><div className="site-container">
        <h2>کاربرد در صنایع مختلف</h2>
        <CardGrid items={INDUSTRIES} className="solutions-industries"/>
      </div></section>

      <section className="site-section solutions-deploy-section"><div className="site-container">
        <h2>کیفیت، امنیت و مدل‌های استقرار</h2>
        <div className="solutions-deploy">{DEPLOY.map((item) => <article key={item.title}>
          <Icon name={item.icon} size={28}/>
          <h3>{item.title}</h3>
          <p>{item.text}</p>
        </article>)}</div>
        <div className="solutions-access">
          <Icon name="shield" size={30}/>
          <div>
            <h3>کنترل دسترسی</h3>
            <p>نقش‌ها و سطوح دسترسی سازمانی تعیین می‌کنند هر کاربر چه اطلاعاتی را ببیند. محدودیت دسترسی دستیار در لایه نرم‌افزار و پیش از ارائه داده به مدل اعمال می‌شود؛ بنابراین محرمانگی صرفاً به پرامپت و رفتار مدل واگذار نمی‌شود.</p>
          </div>
        </div>
        <p className="solutions-note">کیفیت خروجی به وضوح صوت، لهجه، اصطلاحات و شرایط مکالمه وابسته است و اصلاح متن و تحلیل خودکار ممکن است خطا داشته باشد. به همین دلیل درصد دقت یا تضمین برتری نسبت به انسان ارائه نمی‌شود؛ ارزیابی عملی با نمونه واقعی در جلسه دمو پیشنهاد می‌شود.</p>
      </div></section>

      <section className="site-section solutions-roadmap-section"><div className="site-container">
        <h2>قابلیت‌های قابل توسعه</h2>
        <p className="solutions-intro">این موارد در نقشه راه هستند و هنوز به‌عنوان امکان آماده ارائه نمی‌شوند.</p>
        <div className="solutions-roadmap">{ROADMAP.map((item) => <article key={item.title}>
          <span className="solutions-badge">در نقشه راه</span>
          <Icon name={item.icon} size={26}/>
          <h3>{item.title}</h3>
          <p>{item.text}</p>
          <small>{item.note}</small>
        </article>)}</div>
      </div></section>

      <section className="site-section solutions-model-section"><div className="site-container">
        <h2>مدل همکاری</h2>
        <div className="solutions-model">{MODEL.map((item) => <article key={item.title}>
          <Icon name={item.icon} size={26}/>
          <h3>{item.title}</h3>
          <p>{item.text}</p>
        </article>)}</div>
        <p className="solutions-note">قیمت، مدت اجرا، جزئیات مجوز و تعهدات پشتیبانی یا توسعه برای هر سازمان در پیشنهاد فنی و مالی جداگانه تعیین می‌شود.</p>
      </div></section>

      <section className="site-section solutions-start-section"><div className="site-container">
        <h2>شروع همکاری با یک جلسه معرفی</h2>
        <p className="solutions-intro">برای شناخت محصول و تصمیم‌گیری درباره بهره‌برداری، همکاری با یک جلسه معرفی و نمایش عملی صداسنج آغاز می‌شود.</p>
        <ol className="solutions-steps">{STEPS.map((step, index) => <li key={step}>
          <span className="solutions-step-num">{index + 1}</span>
          <span>{step}</span>
        </li>)}</ol>
        <div className="solutions-notes">
          <p>پیشنهاد می‌شود شاخص‌های موفقیت پیش از اجرا تعریف شوند؛ برای نمونه زمان تهیه گزارش روزانه، پوشش ارزیابی مکالمات، کیفیت خروجی صورت‌جلسات و میزان مفید بودن گزارش‌ها برای مدیران. این شاخص‌ها پیشنهادی‌اند و به معنای تضمین نتیجه نیستند.</p>
          <p>در مدل اختصاصی، تهیه سخت‌افزار و نصب مدل‌ها هزینه‌بر است؛ از این‌رو دوره آزمایشی رایگان برای این مدل پیشنهاد پیش‌فرض نیست. کیفیت محصول با نمونه‌های واقعی دارای مجوز نمایش قابل ارزیابی است و شرایط هرگونه پایلوت جداگانه توافق خواهد شد.</p>
        </div>
      </div></section>

      <section className="site-cta"><div className="site-container">
        <h2>صداسنج؛ تصویری روشن‌تر از آنچه در سازمان می‌گذرد</h2>
        <p>برای هماهنگی جلسه معرفی و دریافت پیشنهاد اختصاصی با ما تماس بگیرید.</p>
        <Link className="site-button" to="/contact">هماهنگی جلسه معرفی<Icon name="arrow" size={18}/></Link>
      </div></section>
    </main>
  </PublicPageFrame>;
}
