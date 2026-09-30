import PublicPageFrame from "../components/PublicPageFrame";

export default function Legal({ title }: { title: string }) {
  return <PublicPageFrame><main className="public-main"><section className="public-hero"><div className="landing-container"><span className="public-kicker">اسناد صداسنج</span><h1>{title}</h1><p>متن نهایی این سند پیش از فعال‌سازی پرداخت زنده توسط کسب‌وکار بازبینی و تأیید خواهد شد.</p></div></section></main></PublicPageFrame>;
}
