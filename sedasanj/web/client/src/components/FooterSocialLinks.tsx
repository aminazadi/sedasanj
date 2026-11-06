import { footerSocialNetworks, isSafeFooterSocialUrl, type FooterSettings } from "../../../shared/lib/siteFooter";
import aparat from "../assets/social/aparat.svg";
import bale from "../assets/social/bale.svg";
import eitaa from "../assets/social/eitaa.svg";
import instagram from "../assets/social/instagram.svg";
import telegram from "../assets/social/telegram.svg";
import youtube from "../assets/social/youtube.svg";

// Brand marks from Dashboard Icons (Eitaa, Bale) and Simple Icons.
const icons = { eitaa, bale, telegram, instagram, aparat, youtube };

export default function FooterSocialLinks({ links }: { links: FooterSettings["social_links"] }) {
  const configured = footerSocialNetworks.flatMap(({ key, label }) => {
    const url = links?.[key];
    return url && isSafeFooterSocialUrl(url) ? [{ key, label, url }] : [];
  });
  if (!configured.length) return null;

  return <nav className="site-footer-social" aria-label="شبکه‌های اجتماعی">
    {configured.map(({ key, label, url }) => (
      <a key={key} href={url} target="_blank" rel="noopener noreferrer" aria-label={label} title={label}>
        <img src={icons[key]} alt="" width={24} height={24}/>
      </a>
    ))}
  </nav>;
}
