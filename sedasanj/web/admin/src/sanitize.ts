import DOMPurify from "dompurify";

/** Second layer after the server allowlist; release notes are rendered as HTML. */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target"], FORBID_TAGS: ["style", "img", "iframe"] });
}

export function formatBytes(bytes: number): string {
  const units = ["بایت", "کیلوبایت", "مگابایت", "گیگابایت"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 }).format(value)} ${units[unit]}`;
}
