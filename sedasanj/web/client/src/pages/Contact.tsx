import { useState, type FormEvent } from "react";
import { ApiError, request } from "../api";
import PublicPageFrame from "../components/PublicPageFrame";
import { HeroArt, PageStatus, SafeLink } from "../components/SitePageParts";
import { RichTitle, useSitePage, type ContactContent, type ContactMethod } from "../lib/sitePages";

const ICONS: Record<ContactMethod["icon"], JSX.Element> = {
  mail: <><rect x="3" y="5" width="18" height="14"/><path d="m3 7 9 6 9-6"/></>,
  sales: <><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="13" width="4" height="6"/><rect x="17" y="13" width="4" height="6"/><path d="M17 19c0 1.1-.9 2-2 2h-3"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  phone: <path d="M6.6 2.8 9 8l-2.1 1.8a15.8 15.8 0 0 0 7.3 7.3L16 15l5.2 2.4c.5.2.8.8.6 1.3l-.8 2.2c-.2.7-.9 1.1-1.6 1.1A17.4 17.4 0 0 1 2 4.6c0-.7.4-1.4 1.1-1.6l2.2-.8c.5-.2 1.1.1 1.3.6Z"/>,
  location: <><path d="M12 21s7-6.2 7-11.5A7 7 0 0 0 5 9.5C5 14.8 12 21 12 21Z"/><circle cx="12" cy="9.5" r="2.5"/></>,
  chat: <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z"/>,
};

function MethodBody({ method }: { method: ContactMethod }) {
  return <><i><svg aria-hidden="true" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{ICONS[method.icon] ?? ICONS.chat}</svg></i><span><small>{method.label}</small><strong>{method.value}</strong></span></>;
}

export default function Contact() {
  const { state, reload } = useSitePage<ContactContent>("contact");
  const [status, setStatus] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    setStatus("busy");
    setError("");
    const form = new FormData(formElement);
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
      formElement.reset();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "ارسال درخواست انجام نشد. کمی بعد دوباره تلاش کنید.");
      setStatus("idle");
    }
  }

  if (state.status !== "ready") return <PublicPageFrame><PageStatus state={state.status} onRetry={reload}/></PublicPageFrame>;
  const page = state.content;
  return <PublicPageFrame>
    <main className="page-main contact-page">
      <section className="site-hero page-hero contact-hero"><div className="site-container site-split">
        <div>
        <h1 className="site-hero-title page-title"><RichTitle text={page.hero_title}/></h1><p>{page.hero_text}</p>
        </div>
        <HeroArt/>
      </div></section>

      <section className="contact-content"><div className="site-container contact-layout">
        <aside className="contact-aside">
          <h2>{page.aside_title}</h2>
          <div className="contact-methods">{page.methods.map((method, index) => method.href
            ? <SafeLink key={index} href={method.href}><MethodBody method={method}/></SafeLink>
            : <div key={index}><MethodBody method={method}/></div>)}</div>
        </aside>

        <div className="contact-form-card">
          <div className="contact-form-head"><h2>{page.form_title}</h2></div>
          {status === "done" ? <div className="contact-success" role="status">{page.form_success}</div> : <form onSubmit={submit}>
            <input name="website" tabIndex={-1} autoComplete="off" aria-hidden="true" className="contact-honeypot"/>
            <div className="contact-fields">
              <label><span>نام و نام خانوادگی</span><input name="name" autoComplete="name" required placeholder="نام شما"/></label>
              <label><span>نام سازمان</span><input name="organization" autoComplete="organization" required placeholder="نام مجموعه یا شرکت"/></label>
              <label><span>شماره تماس</span><input name="phone" type="tel" inputMode="tel" autoComplete="tel" required placeholder="۰۹۱۲۱۲۳۴۵۶۷" dir="ltr"/></label>
              <label><span>ایمیل سازمانی</span><input name="email" type="email" autoComplete="email" required placeholder="name@company.com" dir="ltr"/></label>
              <label className="contact-message"><span>موضوع و نیاز شما</span><textarea name="message" required rows={5} placeholder={page.form_message_placeholder}/></label>
            </div>
            {error ? <div className="contact-error" role="alert">{error}</div> : null}
            <button className="site-button" type="submit" disabled={status === "busy"}>{status === "busy" ? "در حال ارسال…" : page.form_submit}</button>
          </form>}
        </div>
      </div></section>
    </main>
  </PublicPageFrame>;
}
