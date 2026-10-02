import type { ReactNode } from "react";

type ConversationBubbleProps = {
  side: "user" | "assistant";
  children: ReactNode;
  header?: ReactNode;
  ariaLabel?: string;
  wide?: boolean;
  actions?: ReactNode;
};

function ConversationAvatar({ side, ariaLabel }: Pick<ConversationBubbleProps, "side" | "ariaLabel">) {
  const user = side === "user";
  const label = ariaLabel ?? (user ? "کاربر" : "دستیار");

  return (
    <span
      className={`assistant-message-avatar flex h-9 w-9 shrink-0 items-center justify-center border ${user ? "border-[#B2AC88] bg-[#F2F0EF] text-[#4B6E48]" : "border-[#4B6E48] bg-[#4B6E48] text-[#F2F0EF]"}`}
      aria-label={label}
      title={label}
    >
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {user ? <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></> : <><path d="M12 3v3" /><rect x="4" y="6" width="16" height="13" rx="3" /><path d="M8 11h.01M16 11h.01M9 15h6" /></>}
      </svg>
    </span>
  );
}

export default function ConversationBubble({ side, children, header, ariaLabel, wide = false, actions }: ConversationBubbleProps) {
  const user = side === "user";

  return (
    <div className={`flex w-full items-end gap-4 ${user ? "justify-end" : "justify-start"}`} dir="ltr">
      {!user ? <ConversationAvatar side={side} ariaLabel={ariaLabel} /> : null}
      <div className={`flex max-w-[calc(85%_-_2.75rem)] flex-col ${wide ? "w-full" : "w-fit"} ${user ? "items-end" : "items-start"}`}>
        <div
          dir="rtl"
          className={`assistant-message-bubble relative w-full break-words rounded-2xl border px-4 py-3 leading-8 shadow-sm ${user ? "assistant-message-bubble-user border-[#4B6E48] bg-[#4B6E48] text-[#F2F0EF]" : "assistant-message-bubble-ai border-[#B2AC88] bg-white text-slate-800"}`}
        >
          {header}
          {children}
        </div>
        {actions ? <div className="mt-1 flex min-h-7 items-center gap-0.5" dir="rtl">{actions}</div> : null}
      </div>
      {user ? <ConversationAvatar side={side} ariaLabel={ariaLabel} /> : null}
    </div>
  );
}
