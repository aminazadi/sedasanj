export interface FooterLink { label: string; url: string }
export const footerSocialNetworks = [
  { key: "eitaa", label: "ایتا" },
  { key: "bale", label: "بله" },
  { key: "telegram", label: "تلگرام" },
  { key: "instagram", label: "اینستاگرام" },
  { key: "aparat", label: "آپارات" },
  { key: "youtube", label: "یوتیوب" },
] as const;
export type FooterSocialNetwork = (typeof footerSocialNetworks)[number]["key"];

export interface FooterSettings {
  contact_title: string;
  contact_description: string;
  about_title: string;
  description: string;
  links_title: string;
  trust_title: string;
  copyright: string;
  address?: string;
  links: FooterLink[];
  legal_links: FooterLink[];
  social_links?: Partial<Record<FooterSocialNetwork, string>>;
}
export interface SiteContactSettingsValue { phone: string; trust_html: string; footer: FooterSettings }

export const defaultFooter: FooterSettings = {
  contact_title: "با ما تماس بگیرید",
  contact_description: "پذیرای صدای گرم شما خواهیم بود",
  about_title: "درباره صداسنج",
  description: "سامانه هوشمند تحلیل مکالمات فارسی",
  links_title: "لینک‌های پرکاربرد",
  trust_title: "نمادهای اعتماد",
  copyright: "© ۱۴۰۵ صداسنج. تمامی حقوق این وب‌سایت برای صداسنج محفوظ است.",
  address: "",
  links: [
    { label: "امکانات", url: "/#features" },
    { label: "پلن‌ها", url: "/#pricing" },
    { label: "درباره ما", url: "/about" },
    { label: "تماس با ما", url: "/contact" },
    { label: "ورود به پنل", url: "/login" },
  ],
  legal_links: [
    { label: "قوانین استفاده", url: "/terms" },
    { label: "حریم خصوصی", url: "/privacy" },
    { label: "لغو اشتراک", url: "/cancellation" },
  ],
};

export function isSafeFooterUrl(url: string): boolean {
  if (/[\s\\\u0000-\u001f]/.test(url)) return false;
  if (url.startsWith("/") && !url.startsWith("//")) return true;
  if (!/^https?:\/\//.test(url)) return false;
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) && !!parsed.hostname && !parsed.username && !parsed.password;
  } catch { return false; }
}

export function isSafeFooterSocialUrl(url: string): boolean {
  return url.startsWith("https://") && isSafeFooterUrl(url);
}
