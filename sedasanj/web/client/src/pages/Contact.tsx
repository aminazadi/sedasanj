import { useState, type FormEvent } from "react";
import { ApiError, request } from "../api";
import PublicPageFrame from "../components/PublicPageFrame";

function ContactIcon({ type }: { type: "mail" | "sales" | "clock" }) {
  const content = type === "mail"
    ? <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></>
    : type === "sales"
      ? <><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="13" width="4" height="6" rx="2"/><rect x="17" y="13" width="4" height="6" rx="2"/><path d="M17 19c0 1.1-.9 2-2 2h-3"/></>
      : <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>;
  return <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{content}</svg>;
}

export default function Contact() {
  const [status, setStatus] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("busy");
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      await request("/v1/contact-leads", { method: "POST", retry: false, body: {
        name: String(form.get("name") ?? "").trim(),
        organization: String(form.get("organization") ?? "").trim(),
        mobile: String(form.get("phone") ?? "").trim(),
        email: String(form.get("email") ?? "").trim(),
        message: String(form.get("message") ?? "").trim(),
        website: String(form.get("website") ?? ""),
        source: "contact_page",
      }});
      setStatus("done");
      event.currentTarget.reset();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "ارسال درخواست انجام نشد.");
      setStatus("idle");
    }
  }

  return <PublicPageFrame>
    <main className="public-main contact-page">
      <section className="public-hero contact-hero"><div className="public-orb public-orb-one"/><div className="landing-container contact-hero-inner"><span className="public-kicker">تماس با صداسنج</span><h1>برای یک تصمیم دقیق‌تر،<br/><em>گفت‌وگو را شروع کنیم.</em></h1><p>برای دریافت دمو، انتخاب پلن مناسب یا بررسی نحوه اتصال صداسنج به مرکز تماس شما، پیام بگذارید.</p></div></section>

      <section className="contact-content"><div className="landing-container contact-layout"><aside className="contact-aside"><div><span>راه‌های ارتباطی</span><h2>کنار شما هستیم.</h2><p>تیم صداسنج برای بررسی نیاز سازمان، راه‌اندازی و پاسخ به پرسش‌های فنی همراه شماست.</p></div><div className="contact-methods"><div><i><ContactIcon type="sales"/></i><span><small>فروش و درخواست دمو</small><strong>فرم مشاوره همین صفحه</strong></span></div><div><i><ContactIcon type="mail"/></i><span><small>پشتیبانی مشتریان</small><strong>از داخل پنل سازمانی</strong></span></div><div><i><ContactIcon type="clock"/></i><span><small>زمان پاسخ‌گویی</small><strong>شنبه تا چهارشنبه، ۹ تا ۱۷</strong></span></div></div><div className="contact-note"><span>برای سازمان‌های بزرگ</span><p>امکان استقرار اختصاصی، ظرفیت سفارشی و طراحی سطح دسترسی متناسب با ساختار سازمان شما وجود دارد.</p></div></aside>

        <div className="contact-form-card"><div className="contact-form-head"><span>درخواست مشاوره</span><h2>کمی از نیازتان برای ما بگویید.</h2><p>درخواست شما مستقیماً برای تیم فروش ثبت می‌شود.</p></div>{status === "done" ? <div className="contact-success">درخواست شما ثبت شد؛ همکاران ما پیگیری می‌کنند.</div> : <form onSubmit={submit}><input name="website" tabIndex={-1} autoComplete="off" className="contact-honeypot"/><div className="contact-fields"><label><span>نام و نام خانوادگی</span><input name="name" autoComplete="name" required placeholder="نام شما" /></label><label><span>نام سازمان</span><input name="organization" autoComplete="organization" required placeholder="نام مجموعه یا شرکت" /></label><label><span>شماره تماس</span><input name="phone" type="tel" inputMode="tel" autoComplete="tel" required placeholder="۰۹۱۲۱۲۳۴۵۶۷" dir="ltr" /></label><label><span>ایمیل سازمانی</span><input name="email" type="email" autoComplete="email" required placeholder="name@company.com" dir="ltr" /></label><label className="contact-message"><span>موضوع و نیاز شما</span><textarea name="message" required rows={5} placeholder="درباره تعداد اپراتورها، حجم تماس یا نوع اتصال مورد نیاز بنویسید." /></label></div>{error ? <div className="commerce-error">{error}</div> : null}<button type="submit" disabled={status === "busy"}>{status === "busy" ? "در حال ارسال…" : "ثبت درخواست"} <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg></button><small>اطلاعات شما فقط برای پاسخ‌گویی به همین درخواست استفاده می‌شود.</small></form>}</div></div></section>
    </main>
  </PublicPageFrame>;
}
