/** Four-square processing mark shared by the assistant and the landing video panel (styles: `.assistant-conversation-processing` in index.css). */
export default function ProcessingIndicator({ active = true, label = "در حال پردازش پاسخ دستیار" }: { active?: boolean; label?: string }) {
  return <span className={`assistant-conversation-processing ${active ? "is-active" : ""}`} role="status" aria-label={label}><span /><span /><span /><span /></span>;
}
