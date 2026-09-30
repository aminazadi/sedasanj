import { Link } from "react-router-dom";
import PublicPageFrame from "../components/PublicPageFrame";

const values = [
  { number: "۰۱", title: "فهم دقیق، نه حدس", text: "تصمیم خوب از داده‌ای شروع می‌شود که شفاف، قابل پیگیری و متصل به مکالمه واقعی باشد." },
  { number: "۰۲", title: "فناوری در خدمت انسان", text: "هوش مصنوعی باید زمان تیم را آزاد کند و در نهایت به تجربه بهتر مشتری و اپراتور برسد." },
  { number: "۰۳", title: "اعتماد در تمام مسیر", text: "حریم داده، کنترل دسترسی و پاسخ‌گویی روشن، بخشی از محصول‌اند؛ نه گزینه‌ای برای بعد." },
];

export default function About() {
  return <PublicPageFrame>
    <main className="public-main">
      <section className="public-hero about-hero"><div className="public-orb public-orb-one"/><div className="public-orb public-orb-two"/><div className="landing-container public-hero-grid"><div><span className="public-kicker">درباره صداسنج</span><h1>برای شنیدن آنچه<br/><em>میان هزاران تماس</em> پنهان می‌ماند.</h1><p>صداسنج برای تبدیل مکالمات روزمره مرکز تماس به دانشی ساخته شده که مدیران بتوانند با آن کیفیت را بسنجند، مسئله‌ها را زودتر ببینند و تصمیم‌های دقیق‌تری بگیرند.</p></div><div className="about-manifesto"><span>دیدگاه ما</span><blockquote>هر مکالمه، بخشی از حقیقت تجربه مشتری را در خود دارد؛ ما آن را قابل دیدن و قابل اقدام می‌کنیم.</blockquote><div><i/><p>از صدای خام تا تصمیم مدیریتی</p></div></div></div></section>

      <section className="public-section"><div className="landing-container about-story"><div className="public-section-heading"><span>مسئله‌ای که حل می‌کنیم</span><h2>فاصله میان شنیدن<br/>و واقعاً فهمیدن</h2></div><div className="about-story-copy"><p>در یک مرکز تماس، اطلاعات ارزشمند اغلب میان ساعت‌ها فایل صوتی گم می‌شوند. بررسی دستی تنها بخش کوچکی از تماس‌ها را پوشش می‌دهد و تصویر نهایی معمولاً دیر، ناقص و وابسته به برداشت فردی است.</p><p>صداسنج این فاصله را با پردازش خودکار مکالمه فارسی، تحلیل محتوا و لحن، ارزیابی عملکرد، استخراج اقدام‌های بعدی و دستیار هوشمند سازمان کوتاه می‌کند.</p><div className="about-flow"><span>مکالمه واقعی</span><i/><span>درک هوشمند</span><i/><span>اقدام روشن</span></div></div></div></section>

      <section className="public-section values-section"><div className="landing-container"><div className="public-section-heading centered"><span>اصولی که با آن می‌سازیم</span><h2>محصولی دقیق، انسانی و قابل اعتماد</h2></div><div className="values-grid">{values.map((value) => <article key={value.number}><b>{value.number}</b><h3>{value.title}</h3><p>{value.text}</p></article>)}</div></div></section>

      <section className="public-section about-outcome"><div className="landing-container outcome-card"><div><span>مسیر مشترک ما</span><h2>هر تماس باید به یک<br/>فرصت برای بهترشدن تبدیل شود.</h2><p>اگر می‌خواهید تصویر دقیق‌تری از صدای مشتریان و عملکرد تیم خود داشته باشید، با ما گفت‌وگو کنید.</p></div><Link to="/contact">گفت‌وگو با تیم صداسنج <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg></Link></div></section>
    </main>
  </PublicPageFrame>;
}
