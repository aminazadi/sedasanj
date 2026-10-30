import { cssUrl } from "../../../shared/lib/cssUrl";

// Explicit URL imports let Vite fingerprint every responsive image variant.
import original0 from "../assets/manager-office-line-art.webp";
import image0_480 from "../assets/manager-office-line-art-480w.webp";
import image0_768 from "../assets/manager-office-line-art-768w.webp";
import original1 from "../assets/pattern.webp";
import image1_480 from "../assets/pattern-480w.webp";
import image1_768 from "../assets/pattern-768w.webp";

const sources = new Map<string, Array<[string, number]>>([
  [original0, [[image0_480, 480], [image0_768, 768], [original0, 1200]]],
  [original1, [[image1_480, 480], [image1_768, 768], [original1, 1440]]],
]);

export function srcSetFor(src: string): string | undefined {
  return sources.get(src)?.map(([url, width]) => `${url} ${width}w`).join(", ");
}

export function cssImageSetFor(src: string): string {
  const candidates = sources.get(src);
  const small = candidates?.find(([, width]) => width >= 480);
  return small ? `image-set(${cssUrl(small[0])} 1x, ${cssUrl(src)} 2x)` : cssUrl(src);
}
