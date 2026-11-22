import { FormEvent, useEffect, useRef, useState } from "react";
import ConversationBubble from "./ConversationBubble";
import MarkdownMessage from "./MarkdownMessage";
import { TypingIndicator } from "../pages/Assistant";
import AssistantMark from "./AssistantMark";

type PublicMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "running" | "succeeded" | "failed";
};

const MAX_HISTORY_TURNS = 12;
const MAX_MESSAGE_LENGTH = 1500;

function CloseIcon() {
  return <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m18 6-12 12M6 6l12 12" /></svg>;
}

function SendIcon() {
  return <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>;
}

// No server storage for the public widget: history lives only in this component's state
// and is lost on reload or navigation (the conversation is never persisted or tenant-scoped).
export default function PublicAssistantWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<PublicMessage[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) window.setTimeout(() => inputRef.current?.focus(), 100);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  async function send(content: string, history: PublicMessage[]) {
    setSending(true);
    setError(null);
    const draftId = `public-assistant-${Date.now()}`;
    setMessages([...history, { id: `${draftId}-user`, role: "user", content, status: "succeeded" }, { id: draftId, role: "assistant", content: "", status: "running" }]);
    try {
      const response = await fetch("/v1/public-assistant/messages/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content,
          history: history.slice(-MAX_HISTORY_TURNS).map((item) => ({ role: item.role, content: item.content.slice(0, MAX_MESSAGE_LENGTH) })),
        }),
      });
      if (!response.ok || !response.body) {
        let message = response.statusText;
        try { message = (await response.json())?.error?.message ?? message; } catch { /* non-JSON error body */ }
        throw new Error(message);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;
      const handleFrame = (frame: string) => {
        const lines = frame.split(/\r?\n/);
        const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
        const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).replace(/^ /, "")).join("\n");
        if (!event || !data) return;
        const payload = JSON.parse(data) as { content?: string };
        if (event === "delta" && payload.content !== undefined) setMessages((current) => current.map((item) => item.id === draftId ? { ...item, content: item.content + (payload.content || "") } : item));
        if (event === "replace" && payload.content !== undefined) setMessages((current) => current.map((item) => item.id === draftId ? { ...item, content: payload.content || "" } : item));
        if (event === "done") finished = true;
      };
      try {
        while (true) {
          const { done, value } = await reader.read();
          buffer += decoder.decode(value, { stream: !done });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() ?? "";
          frames.forEach(handleFrame);
          if (done) {
            if (buffer.trim()) handleFrame(buffer);
            break;
          }
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
      setMessages((current) => current.map((item) => item.id === draftId ? { ...item, status: finished ? "succeeded" : "failed" } : item));
    } catch (err) {
      const message = (err as Error).message || "پاسخ هوشیار آماده نشد.";
      setMessages((current) => current.map((item) => item.id === draftId ? { ...item, content: item.content || message, status: "failed" } : item));
      setError(message);
    } finally {
      setSending(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const content = text.trim();
    if (!content || sending) return;
    setText("");
    await send(content.slice(0, MAX_MESSAGE_LENGTH), messages.filter((message) => message.status !== "running"));
  }

  return <div className="quick-assistant-root" dir="rtl">
    {open ? <button type="button" className="fixed inset-0 z-[60] bg-slate-950/25 backdrop-blur-[1px]" onClick={() => setOpen(false)} aria-label="بستن هوشیار" /> : null}
    <section className={`quick-assistant-panel fixed bottom-5 left-5 z-[70] flex h-[min(38rem,calc(100dvh-2.5rem))] w-[min(27rem,calc(100vw-2.5rem))] origin-bottom-left flex-col overflow-hidden border border-[color:var(--line)] bg-[var(--color-canvas)] shadow-[0_24px_70px_rgba(34,55,32,0.34)] transition-[transform,opacity] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] ${open ? "scale-100 opacity-100" : "pointer-events-none scale-[0.14] opacity-0"}`} aria-hidden={!open} aria-label="هوشیار">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[color:var(--line)] bg-[var(--color-primary)] px-4 py-3 text-white">
        <div><h2 className="text-sm font-bold">هوشیار</h2><p className="text-[11px] text-[#D8D3B9]">راهنمای صداسنج و جلسه‌نگار</p></div>
        <button type="button" className="p-1.5 transition hover:bg-white/15" onClick={() => setOpen(false)} aria-label="بستن هوشیار"><CloseIcon /></button>
      </header>
      <div ref={scrollerRef} className="sidebar-scroll flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 ? <div className="mx-auto flex h-full min-h-[18rem] max-w-sm flex-col items-center justify-center gap-3 text-center text-[var(--color-neutral)]">
          <div className="relative flex items-center justify-center">
            <span className="absolute h-40 w-40 rounded-full bg-[rgb(var(--color-primary-rgb)/0.1)] blur-2xl" aria-hidden="true" />
            <AssistantMark className="relative h-24 w-24" />
          </div>
          <div className="space-y-2">
            <h3 className="text-base font-extrabold tracking-tight text-[var(--ink)]">سلام، من هوشیارم</h3>
            <p className="text-sm leading-7">چه کمکی از دستم برمی‌آید؟</p>
          </div>
        </div> : null}
        {messages.map((message) => {
          const user = message.role === "user";
          if (!user && message.status === "running" && !message.content) return <div key={message.id} className="flex items-end justify-start gap-4">
            <span className="assistant-message-avatar flex h-9 w-9 shrink-0 items-center justify-center" aria-hidden="true"><AssistantMark className="h-9 w-9" animated={false} /></span>
            <TypingIndicator />
          </div>;
          return <ConversationBubble key={message.id} side={user ? "user" : "assistant"} aiAvatar>
            <MarkdownMessage content={message.content} />
          </ConversationBubble>;
        })}
      </div>
      {error ? <p className="shrink-0 border-t border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p> : null}
      <form className="assistant-composer relative shrink-0 border-t border-[color:var(--line)] bg-canvas" onSubmit={(event) => void submit(event)}>
        <div className="flex flex-col bg-[var(--color-canvas)]">
          <textarea ref={inputRef} rows={1} maxLength={MAX_MESSAGE_LENGTH} className="input block h-[3rem] min-h-[3rem] w-full resize-none border-0 bg-transparent px-3 pb-1 pt-3 text-sm text-slate-900 !shadow-none focus:!border-0 focus:!shadow-none focus:!outline-none" value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.ctrlKey && event.key === "Enter") event.currentTarget.form?.requestSubmit(); }} placeholder="سؤال خود را بنویسید…" aria-label="پیام به هوشیار" />
          <div className="flex min-w-0 items-center gap-2 px-3 pb-3 pt-2">
            <span className="flex-1" />
            <button type="submit" className="inline-flex h-9 shrink-0 items-center justify-center gap-2 bg-[var(--color-primary)] px-4 text-sm font-bold text-white transition hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] disabled:cursor-not-allowed disabled:bg-[var(--color-accent)] disabled:text-white" disabled={sending || !text.trim()} aria-label="ارسال پیام" title="ارسال پیام (Ctrl+Enter)">
              <SendIcon /><span>ارسال</span>
            </button>
          </div>
        </div>
      </form>
    </section>
    <button id="public-assistant-trigger" type="button" className={`quick-assistant-trigger fixed bottom-5 left-5 z-[65] inline-flex h-16 w-16 items-center justify-center transition hover:scale-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] ${open ? "pointer-events-none scale-90 opacity-0" : ""}`} onClick={() => setOpen(true)} aria-label="باز کردن هوشیار">
      <AssistantMark className="h-16 w-16 drop-shadow-[0_10px_20px_rgba(34,55,32,0.35)]" />
    </button>
  </div>;
}
