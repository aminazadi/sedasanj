import { cssUrl } from "../../../shared/lib/cssUrl";

// Explicit URL imports let Vite fingerprint every responsive image variant.
import original0 from "../assets/hero-call-center.webp";
import image0_480 from "../assets/hero-call-center-480w.webp";
import image0_768 from "../assets/hero-call-center-768w.webp";
import original1 from "../assets/hero-office.webp";
import image1_480 from "../assets/hero-office-480w.webp";
import image1_768 from "../assets/hero-office-768w.webp";
import original2 from "../assets/manager-office-line-art.webp";
import image2_480 from "../assets/manager-office-line-art-480w.webp";
import image2_768 from "../assets/manager-office-line-art-768w.webp";
import original4 from "../assets/page-hero-about.webp";
import image4_480 from "../assets/page-hero-about-480w.webp";
import image4_768 from "../assets/page-hero-about-768w.webp";
import original5 from "../assets/page-hero-contact.webp";
import image5_480 from "../assets/page-hero-contact-480w.webp";
import image5_768 from "../assets/page-hero-contact-768w.webp";
import original6 from "../assets/page-hero-help.webp";
import image6_480 from "../assets/page-hero-help-480w.webp";
import image6_768 from "../assets/page-hero-help-768w.webp";
import original7 from "../assets/page-hero-legal.webp";
import image7_480 from "../assets/page-hero-legal-480w.webp";
import image7_768 from "../assets/page-hero-legal-768w.webp";
import original8 from "../assets/pattern.webp";
import image8_480 from "../assets/pattern-480w.webp";
import image8_768 from "../assets/pattern-768w.webp";
import original9 from "../assets/phone-auth-dialog.webp";
import image9_480 from "../assets/phone-auth-dialog-480w.webp";
import image9_768 from "../assets/phone-auth-dialog-768w.webp";
import original10 from "../assets/phone-auth-organization.webp";
import image10_480 from "../assets/phone-auth-organization-480w.webp";
import image10_768 from "../assets/phone-auth-organization-768w.webp";
import original11 from "../assets/phone-auth-otp.webp";
import image11_480 from "../assets/phone-auth-otp-480w.webp";
import image11_768 from "../assets/phone-auth-otp-768w.webp";
import original12 from "../assets/quick-demo-agent.webp";
import image12_480 from "../assets/quick-demo-agent-480w.webp";
import image12_768 from "../assets/quick-demo-agent-768w.webp";
import original13 from "../assets/quick-demo-recording-review.webp";
import image13_480 from "../assets/quick-demo-recording-review-480w.webp";
import image13_768 from "../assets/quick-demo-recording-review-768w.webp";
import original14 from "../assets/quick-demo-voip-integration.webp";
import image14_480 from "../assets/quick-demo-voip-integration-480w.webp";
import image14_768 from "../assets/quick-demo-voip-integration-768w.webp";
import original15 from "../assets/sedasanj-refined-master.webp";
import image15_480 from "../assets/sedasanj-refined-master-480w.webp";
import original16 from "../assets/telephony-integration-banner-desktop.webp";
import image16_480 from "../assets/telephony-integration-banner-desktop-480w.webp";
import image16_768 from "../assets/telephony-integration-banner-desktop-768w.webp";

const sources = new Map<string, Array<[string, number]>>([
  [original0, [[image0_480, 480], [image0_768, 768], [original0, 1620]]],
  [original1, [[image1_480, 480], [image1_768, 768], [original1, 1774]]],
  [original2, [[image2_480, 480], [image2_768, 768], [original2, 1200]]],
  [original4, [[image4_480, 480], [image4_768, 768], [original4, 1500]]],
  [original5, [[image5_480, 480], [image5_768, 768], [original5, 1500]]],
  [original6, [[image6_480, 480], [image6_768, 768], [original6, 1500]]],
  [original7, [[image7_480, 480], [image7_768, 768], [original7, 1500]]],
  [original8, [[image8_480, 480], [image8_768, 768], [original8, 1440]]],
  [original9, [[image9_480, 480], [image9_768, 768], [original9, 1000]]],
  [original10, [[image10_480, 480], [image10_768, 768], [original10, 1000]]],
  [original11, [[image11_480, 480], [image11_768, 768], [original11, 1000]]],
  [original12, [[image12_480, 480], [image12_768, 768], [original12, 1200]]],
  [original13, [[image13_480, 480], [image13_768, 768], [original13, 1000]]],
  [original14, [[image14_480, 480], [image14_768, 768], [original14, 1000]]],
  [original15, [[image15_480, 480], [original15, 1040]]],
  [original16, [[image16_480, 480], [image16_768, 768], [original16, 1600]]],
]);

export function srcSetFor(src: string): string | undefined {
  return sources.get(src)?.map(([url, width]) => `${url} ${width}w`).join(", ");
}

export function cssImageSetFor(src: string): string {
  const candidates = sources.get(src);
  const small = candidates?.find(([, width]) => width >= 480);
  return small ? `image-set(${cssUrl(small[0])} 1x, ${cssUrl(src)} 2x)` : cssUrl(src);
}
