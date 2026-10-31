/** Four-square processing mark shared by the assistant, the landing video panel and every spinner in the client app (styles: `.assistant-conversation-processing` in index.css). */
export default function ProcessingIndicator({ active = true, size = "sm", label = "در حال پردازش پاسخ دستیار", className = "" }: { active?: boolean; size?: "sm" | "md" | "lg"; label?: string; className?: string }) {
  return <span className={`assistant-conversation-processing ${active ? "is-active" : ""} ${size === "sm" ? "" : `assistant-conversation-processing--${size}`} ${className}`.trim()} role="status" aria-label={label}><span /><span /><span /><span /></span>;
}
