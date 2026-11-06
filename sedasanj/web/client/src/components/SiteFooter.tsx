import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { defaultFooter, isSafeFooterUrl, type FooterLink, type SiteContactSettingsValue } from "../../../shared/lib/siteFooter";
import { request } from "../api";
import logo from "../assets/sedasanj-refined-master.webp";
import FooterSocialLinks from "./FooterSocialLinks";

export default function SiteFooter() {
  const [siteContact, setSiteContact] = useState<SiteContactSettingsValue>({ phone: "09399093062", trust_html: "", footer: defaultFooter });
  useEffect(() => {
    request<SiteContactSettingsValue>("/v1/site/contact-settings")
      .then((value) => setSiteContact({ ...value, footer: value.footer ?? defaultFooter }))
      .catch(() => undefined);
  }, []);
  const footer = siteContact.footer;
  function renderLink(link: FooterLink, index: number) {
    if (!isSafeFooterUrl(link.url)) return null;
    return link.url.startsWith("/")
      ? <Link key={index} to={link.url}>{link.label}</Link>
      : <a key={index} href={link.url}>{link.label}</a>;
  }
  return (
    <footer className="site-footer">
      <section className="site-footer-contact" aria-labelledby="site-footer-contact-title">
        <div className="site-container site-footer-contact-inner">
          <div><h2 id="site-footer-contact-title">{footer.contact_title}</h2><p>{footer.contact_description}</p></div>
          <a className="site-footer-phone" href={`tel:${siteContact.phone}`} dir="rtl">{siteContact.phone.replace(/\d/g, (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)])}</a>
        </div>
      </section>
      <div className="site-container site-footer-main">
        <div className="site-footer-brand">
          <Link to="/" aria-label="صداسنج، صفحه اصلی"><img className="site-logo" src={logo} alt="صداسنج"/></Link>
          <p>{footer.description}</p>
          <FooterSocialLinks links={footer.social_links}/>
        </div>
        <nav className="site-footer-links" aria-label={footer.links_title || "لینک‌های پرکاربرد"}>{footer.links_title && <strong>{footer.links_title}</strong>}{footer.links.map(renderLink)}</nav>
        <nav className="site-footer-legal" aria-label="قوانین و حریم خصوصی">{footer.legal_links.map(renderLink)}</nav>
        <div className="site-footer-trust" aria-label="نمادهای اعتماد"><strong>{footer.trust_title}</strong>{siteContact.trust_html ? <iframe className="site-footer-trust-frame" title="نمادهای اعتماد صداسنج" sandbox="allow-scripts" srcDoc={siteContact.trust_html}/> : <div className="site-footer-trust-slots"><span aria-hidden="true">جایگاه نماد</span><span aria-hidden="true">جایگاه نماد</span></div>}</div>
      </div>
      <div className="site-container site-footer-bottom" dir="rtl">
        <small>{footer.copyright}</small>
        <small className="site-footer-credit" dir="ltr" lang="en">
          developed with ❤️ by <a href="https://t.me/Robolink_F1">ROBOLINK</a>
        </small>
      </div>
    </footer>
  );
}
