import AssistantContextPicker, { AssistantAttachmentChips } from "./AssistantContextPicker";
import { exportFiles } from "./assistantExportLinks.mjs";
import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, refreshSession, request, tokens } from "../api";
import { isOrgAdmin, useAuth } from "../auth";
import { CallSources, ToolTimeline, TypingIndicator } from "../pages/Assistant";
import { AssistantCharts } from "./AssistantCharts";
import type { AssistantChart, AssistantContextOptions, AssistantMessageAttachments, AssistantToolRun, ChatConversation, ChatMessage } from "../types";
import ConversationBubble from "./ConversationBubble";
import MarkdownMessage from "./MarkdownMessage";
import PersianSpeechInputButton from "./PersianSpeechInputButton";
import AssistantMark from "./AssistantMark";

const emptyAttachments = (): AssistantMessageAttachments => ({
  operator_id: null,
  conversation_ids: [],
  from_date: null,
  to_date: null,
  tool_names: [],
});

function AssistantIcon({ className = "h-11 w-11" }: { className?: string }) {
  return <AssistantMark className={className} />;
}

function CloseIcon() {
  return <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m18 6-12 12M6 6l12 12" /></svg>;
}

function SendIcon() {
  return <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>;
}

function StopIcon() {
  return <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="1" /></svg>;
}

function CopyIcon({ checked }: { checked: boolean }) {
  return <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">{checked ? <path d="m5 12 4 4L19 6" /> : <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" /></>}</svg>;
}

function EditIcon() {
  return <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></svg>;
}

function RetryIcon() {
  return <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M20 7v5h-5M19 12a7 7 0 1 0-2 5" /></svg>;
}

export default function QuickAssistantWidget() {
  const { session } = useAuth();
  const [search, setSearch] = useSearchParams();
  const open = search.get("assistant_widget") === "open";
  const [conversation, setConversation] = useState<ChatConversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const speechPrefixRef = useRef("");
  const [attachments, setAttachments] = useState<AssistantMessageAttachments>(emptyAttachments);
  const [contextOptions, setContextOptions] = useState<AssistantContextOptions | null>(null);
  const [mentionOpen, setMentionOpen] = useState(false);
  const selectedContextTab = search.get("assistant_widget_tab");
  const mentionTab = selectedContextTab === "dates" ? selectedContextTab : "mentions";
  function selectMentionTab(tab: "mentions" | "dates" | "tools") {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      next.set("assistant_widget_tab", tab);
      return next;
    }, { replace: true });
  }
  const [mentionAnchor, setMentionAnchor] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phases, setPhases] = useState<Record<string, string>>({});
  const [expandedCallId, setExpandedCallId] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ message: ChatMessage; value: string } | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLFormElement>(null);
  const requestControllerRef = useRef<AbortController | null>(null);

  const close = () => setSearch((current) => {
    const next = new URLSearchParams(current);
    next.delete("assistant_widget");
    return next;
  }, { replace: true });

  const show = () => setSearch((current) => {
    const next = new URLSearchParams(current);
    next.set("assistant_widget", "open");
    return next;
  }, { replace: true });

  useEffect(() => {
    if (!open) return;
    setConversation(null);
    setMessages([]);
    setText("");
    setAttachments(emptyAttachments());
    setError(null);
    setMentionOpen(false);
    void request<AssistantContextOptions>("/v1/assistant/context-options").then(setContextOptions).catch((err) => setError((err as Error).message));
    window.setTimeout(() => inputRef.current?.focus(), 100);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (event.target instanceof Element && event.target.closest("[data-date-picker-panel]")) return;
        if (mentionOpen) setMentionOpen(false);
        else close();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, mentionOpen]);

  useEffect(() => {
    if (!mentionOpen) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (event.target instanceof Element && event.target.closest("[data-date-picker-panel]")) return;
      if (!composerRef.current?.contains(event.target as Node)) setMentionOpen(false);
    };
    document.addEventListener("click", closeOnOutsideClick);
    return () => document.removeEventListener("click", closeOnOutsideClick);
  }, [mentionOpen]);

  useEffect(() => {
    if (!open) return;
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, open]);

  async function createConversation() {
    const item = await request<ChatConversation>("/v1/assistant/conversations", { method: "POST", body: { call_id: null } });
    setConversation(item);
    return item;
  }

  async function streamReply(conversationId: string, content: string, draftId: string, messageAttachments: AssistantMessageAttachments, signal: AbortSignal) {
    const makeRequest = () => fetch(`/v1/assistant/conversations/${conversationId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(tokens.access() ? { Authorization: `Bearer ${tokens.access()}` } : {}) },
      body: JSON.stringify({ content, attachments: messageAttachments }),
      signal,
    });
    let response = await makeRequest();
    if (response.status === 401 && await refreshSession()) response = await makeRequest();
    if (!response.ok || !response.body) {
      let message = response.statusText;
      try { message = (await response.json())?.error?.message ?? message; } catch { /* non-JSON error body */ }
      throw new Error(message);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed: ChatMessage | null = null;
    const handleFrame = (frame: string) => {
      const lines = frame.split(/\r?\n/);
      const event = lines.find((line) => line.startsWith("event:"))?.slice(6).trim();
      const data = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).replace(/^ /, "")).join("\n");
      if (!event || !data) return;
      const payload = JSON.parse(data) as { content?: string; message?: ChatMessage; label?: string; tool_call_id?: string; name?: string; title?: string; status?: AssistantToolRun["status"]; duration_ms?: number; summary?: string; error_code?: string; charts?: AssistantChart[]; files?: AssistantToolRun["files"] };
      if (event === "phase" && payload.label) setPhases((current) => ({ ...current, [draftId]: payload.label as string }));
      if ((event === "tool_started" || event === "tool_completed" || event === "tool_failed") && payload.tool_call_id && payload.name && payload.title) {
        const run: AssistantToolRun = { tool_call_id: payload.tool_call_id, name: payload.name, title: payload.title, status: payload.status || (event === "tool_started" ? "running" : event === "tool_failed" ? "failed" : "succeeded"), duration_ms: payload.duration_ms ?? null, summary: payload.summary ?? null, error_code: payload.error_code ?? null, charts: payload.charts || [], files: payload.files || [] };
        setMessages((current) => current.map((item) => item.id === draftId ? { ...item, tool_runs: [...(item.tool_runs || []).filter((itemRun) => itemRun.tool_call_id !== run.tool_call_id), run] } : item));
      }
      if ((event === "delta" || event === "replace") && payload.content !== undefined) setMessages((current) => current.map((item) => item.id === draftId ? { ...item, content: event === "replace" ? payload.content || "" : item.content + (payload.content || "") } : item));
      if (event === "done" && payload.message) completed = payload.message;
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
      if (!completed) throw new Error("پاسخ دستیار کامل نشد.");
      setMessages((current) => current.map((item) => item.id === draftId ? completed as ChatMessage : item));
    } finally {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  }

  async function send(content: string, history: ChatMessage[], messageAttachments: AssistantMessageAttachments) {
    setSending(true);
    setError(null);
    const controller = new AbortController();
    requestControllerRef.current = controller;
    const optimistic: ChatMessage = { id: `widget-user-${Date.now()}`, role: "user", content, status: "succeeded", model: null, sources: null, attachments: messageAttachments, tool_runs: [], created_at: new Date().toISOString() };
    const draft: ChatMessage = { id: `widget-assistant-${Date.now()}`, role: "assistant", content: "", status: "running", model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() };
    try {
      const active = conversation ?? await createConversation();
      setMessages([...history, optimistic, draft]);
      await streamReply(active.id, content, draft.id, messageAttachments, controller.signal);
      setAttachments(emptyAttachments());
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        setMessages((current) => current.map((item) => item.id === draft.id ? { ...item, content: "پاسخ متوقف شد.", status: "cancelled" } : item));
        return;
      }
      const message = (err as Error).message || "پاسخ دستیار آماده نشد.";
      setMessages((current) => current.map((item) => item.id === draft.id ? { ...item, content: message, status: "failed" } : item));
      setError(message);
    } finally {
      if (requestControllerRef.current === controller) requestControllerRef.current = null;
      setSending(false);
    }
  }

  function interruptMessage() {
    requestControllerRef.current?.abort();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || sending) return;
    if (Boolean(attachments.from_date) !== Boolean(attachments.to_date)) {
      setError("برای بازه زمانی، تاریخ شروع و پایان را کامل انتخاب کنید.");
      setMentionOpen(true);
      selectMentionTab("dates");
      return;
    }
    const content = text.trim();
    window.dispatchEvent(new Event("assistant-message-sent"));
    setText("");
    await send(content, messages.filter((message) => message.status !== "running"), attachments);
  }

  async function replaceMessage(message: ChatMessage, content: string) {
    if (!conversation || sending) return;
    const index = messages.findIndex((item) => item.id === message.id);
    if (index < 0) return;
    try {
      setSending(true);
      await request(`/v1/assistant/conversations/${conversation.id}/messages/${message.id}/tail`, { method: "DELETE" });
      setEditing(null);
      await send(content.trim(), messages.slice(0, index).filter((item) => item.status !== "running"), message.attachments || emptyAttachments());
    } catch (err) {
      setError((err as Error).message);
      setSending(false);
    }
  }

  const mentionStart = mentionAnchor ?? -1;
  const mentionQuery = mentionStart >= 0 && text[mentionStart] === "@" ? text.slice(mentionStart + 1).trim().toLocaleLowerCase("fa") : "";
  const matchingOperators = isOrgAdmin(session?.role) ? (contextOptions?.operators || []).filter((item) => `${item.label} ${item.extension || ""}`.toLocaleLowerCase("fa").includes(mentionQuery)) : [];
  const matchingConversations = (contextOptions?.conversations || []).filter((item) => item.label.toLocaleLowerCase("fa").includes(mentionQuery));
  const actionClass = "inline-flex h-7 w-7 items-center justify-center text-[var(--color-neutral)] transition hover:bg-canvas hover:text-[var(--color-primary)] disabled:opacity-50";

  if (!session || (session.role !== "org_admin" && session.role !== "operator")) return null;
  return <div className="quick-assistant-root" dir="rtl">
    {open ? <button type="button" className="fixed inset-0 z-[60] bg-slate-950/25 backdrop-blur-[1px]" onClick={close} aria-label="بستن چت سریع دستیار" /> : null}
    <section className={`quick-assistant-panel fixed bottom-5 left-5 z-[70] flex h-[min(44rem,calc(100dvh-2.5rem))] w-[min(31rem,calc(100vw-2.5rem))] origin-bottom-left flex-col overflow-hidden border border-[color:var(--line)] bg-[var(--color-canvas)] shadow-[0_24px_70px_rgba(34,55,32,0.34)] transition-[transform,opacity] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] ${open ? "scale-100 opacity-100" : "pointer-events-none scale-[0.14] opacity-0"}`} aria-hidden={!open} aria-label="چت سریع دستیار">
      <header className="flex shrink-0 items-center justify-between gap-3 border-b border-[color:var(--line)] bg-[var(--color-primary)] px-4 py-3 text-white"><div><h2 className="text-sm font-bold">دستیار تماس‌ها</h2><p className="text-[11px] text-[#D8D3B9]">گفتگوی جدید</p></div><div className="flex items-center gap-1"><Link to="/assistant" className="border border-[color:var(--line)] px-2 py-1 text-xs font-bold transition hover:bg-[var(--color-canvas)] hover:text-[var(--color-primary)]">صفحه کامل</Link><button type="button" className="p-1.5 transition hover:bg-white/15" onClick={close} aria-label="بستن چت سریع"><CloseIcon /></button></div></header>
      <div ref={scrollerRef} className="sidebar-scroll flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 ? <div className="mx-auto flex h-full min-h-[22rem] max-w-sm flex-col items-center justify-center gap-3 text-center text-[var(--color-neutral)]">
          <div className="relative flex items-center justify-center">
            <span className="absolute h-40 w-40 rounded-full bg-[rgb(var(--color-primary-rgb)/0.1)] blur-2xl" aria-hidden="true" />
            <AssistantIcon className="relative h-28 w-28" />
          </div>
          <div className="space-y-2">
            <h3 className="text-base font-extrabold tracking-tight text-[var(--ink)]">من هوشیارم، چه کمکی از من ساخته‌ست؟</h3>
            <p className="text-sm leading-7">درباره تماس‌ها، تحلیل‌ها و عملکرد اپراتورها سؤال کنید.</p>
          </div>
        </div> : null}
        {messages.map((message) => {
          const user = message.role === "user";
          const charts = (message.tool_runs || []).flatMap((run) => run.charts || []);
          const actions = <><span className="flex items-center gap-0.5" dir="rtl">{user && message.status !== "running" ? <button type="button" className={actionClass} disabled={sending} onClick={() => setEditing({ message, value: message.content })} aria-label="ویرایش پیام"><EditIcon /></button> : null}{message.status !== "running" && message.content ? <button type="button" className={actionClass} onClick={() => void navigator.clipboard.writeText(message.content).then(() => { setCopiedMessageId(message.id); window.setTimeout(() => setCopiedMessageId(null), 1600); }).catch(() => setError("کپی پیام انجام نشد."))} aria-label="کپی پیام"><CopyIcon checked={copiedMessageId === message.id} /></button> : null}{!user && message.status === "failed" ? <button type="button" className={actionClass} disabled={sending} onClick={() => { const previous = [...messages.slice(0, messages.indexOf(message))].reverse().find((item) => item.role === "user"); if (previous) void replaceMessage(previous, previous.content); }} aria-label="تلاش مجدد"><RetryIcon /></button> : null}</span><time className="text-[10px] text-[var(--color-neutral)]">{fmt.time(message.created_at)}</time></>;
          if (!user && message.status === "running" && !message.content) return <div key={message.id} className="flex items-end justify-start gap-4">
            <span className="assistant-message-avatar flex h-9 w-9 shrink-0 items-center justify-center" aria-hidden="true"><AssistantMark className="h-9 w-9" animated={false} /></span>
            <TypingIndicator label={phases[message.id]} />
          </div>;
          return <ConversationBubble key={message.id} side={user ? "user" : "assistant"} wide={Boolean(message.sources?.length || charts.length)} actions={actions} aiAvatar>{editing?.message.id === message.id ? <div className="space-y-2"><textarea autoFocus rows={3} className="input min-h-24 resize-y bg-canvas text-slate-900" value={editing.value} onChange={(event) => setEditing({ message, value: event.target.value })} /><div className="flex justify-end gap-2"><button type="button" className="border border-[color:var(--line)] px-3 py-1 text-xs" onClick={() => setEditing(null)}>انصراف</button><button type="button" className="bg-[var(--color-canvas)] px-3 py-1 text-xs font-bold text-[var(--color-primary)]" disabled={!editing.value.trim() || sending} onClick={() => void replaceMessage(message, editing.value)}>ثبت</button></div></div> : <>{user && message.attachments ? <div className="mb-2 flex flex-wrap gap-1 text-xs text-[var(--color-canvas)]"><span>{message.attachments.operator_id ? "اپراتور انتخاب شده" : ""}</span>{message.attachments.from_date ? <span>بازه زمانی انتخاب شده</span> : null}</div> : null}{!user ? <ToolTimeline runs={message.tool_runs || []} active={message.status === "running"} /> : null}<MarkdownMessage content={message.content} files={user ? [] : exportFiles(message.tool_runs || [])} />{!user ? <AssistantCharts charts={charts} /> : null}{message.sources?.length ? <CallSources sources={message.sources} expandedCallId={expandedCallId} onToggle={(callId) => setExpandedCallId((current) => current === callId ? null : callId)} /> : null}</>}</ConversationBubble>;
        })}
      </div>
      {error ? <p className="shrink-0 border-t border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p> : null}
      <form ref={composerRef} className="assistant-composer relative shrink-0 border-t border-[color:var(--line)] bg-canvas" onSubmit={(event) => void submit(event)}>
        {mentionOpen ? <AssistantContextPicker tab={mentionTab} onTabChange={selectMentionTab} onClose={() => { setMentionOpen(false); inputRef.current?.focus(); }} attachments={attachments} onChange={setAttachments} options={contextOptions}>
          {mentionTab === "mentions" ? <>{matchingOperators.map((item) => <button key={item.id} type="button" className="block w-full px-2 py-2 text-right text-sm hover:bg-[var(--color-canvas)]" onClick={() => { setAttachments((current) => ({ ...current, operator_id: item.id })); setMentionOpen(false); setText((current) => mentionStart >= 0 ? current.slice(0, mentionStart).trimEnd() : current); }}>{item.label}</button>)}{matchingConversations.map((item) => <button key={item.id} type="button" className="block w-full px-2 py-2 text-right text-sm hover:bg-[var(--color-canvas)]" onClick={() => { setAttachments((current) => ({ ...current, conversation_ids: current.conversation_ids.includes(item.id) ? current.conversation_ids : [...current.conversation_ids, item.id] })); setMentionOpen(false); setText((current) => mentionStart >= 0 ? current.slice(0, mentionStart).trimEnd() : current); }}>{item.label}</button>)}</> : null}
        </AssistantContextPicker> : null}
        {<AssistantAttachmentChips attachments={attachments} options={contextOptions} onChange={setAttachments} />}
<div className={`flex flex-col transition ${listening ? "bg-[var(--color-selected)]" : "bg-[var(--color-canvas)]"}`}><textarea ref={inputRef} rows={1} className="input block h-[3rem] min-h-[3rem] w-full resize-none border-0 bg-transparent px-3 pb-1 pt-3 text-sm text-slate-900 !shadow-none focus:!border-0 focus:!shadow-none focus:!outline-none" value={text} onChange={(event) => { const value = event.target.value; setText(value); const anchor = value.lastIndexOf("@"); if (anchor >= 0 && anchor === value.length - 1) { setMentionAnchor(anchor); selectMentionTab("mentions"); setMentionOpen(true); } }} onKeyDown={(event) => { if (event.ctrlKey && event.key === "Enter") event.currentTarget.form?.requestSubmit(); }} placeholder={listening ? "در حال شنیدن گفتار فارسی…" : "سؤال خود را بنویسید…"} aria-label="پیام به دستیار" /><div className="assistant-composer-actions flex min-w-0 items-center gap-2 px-3 pb-3 pt-2"><div className="flex shrink-0 items-center gap-1.5"><PersianSpeechInputButton className={`inline-flex h-8 items-center gap-1.5 border px-2.5 text-xs font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-50 ${listening ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-white" : "border-[var(--color-accent)] bg-canvas text-[var(--color-primary)] hover:border-[var(--color-primary)] hover:bg-[var(--color-selected)]"}`} onTranscript={({ final, interim }) => { setText(`${speechPrefixRef.current}${speechPrefixRef.current && (final || interim) ? " " : ""}${final}${final && interim ? " " : ""}${interim}`); inputRef.current?.focus(); }} onListeningChange={(active) => { if (active) speechPrefixRef.current = text; setListening(active); }} stopWhen={sending} /><button type="button" className="inline-flex h-8 items-center gap-1.5 border border-[var(--color-accent)] bg-canvas px-2.5 text-xs font-bold text-[var(--color-primary)] transition hover:border-[var(--color-primary)] hover:bg-[var(--color-selected)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--color-primary)]" aria-haspopup="dialog" aria-expanded={mentionOpen && mentionTab === "dates"} onClick={() => { setMentionAnchor(null); selectMentionTab("dates"); setMentionOpen((current) => mentionTab === "dates" ? !current : true); }}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-3.5 w-3.5"><path d="M7 3v3m10-3v3M4 9h16M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1Z" /></svg>بازه زمانی</button></div><span className="flex-1" /><button type={sending ? "button" : "submit"} onClick={sending ? interruptMessage : undefined} className="inline-flex h-9 shrink-0 items-center justify-center gap-2 bg-[var(--color-primary)] px-4 text-sm font-bold text-white transition hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] disabled:cursor-not-allowed disabled:bg-[var(--color-accent)] disabled:text-white" disabled={!sending && !text.trim()} aria-label={sending ? "قطع پاسخ" : "ارسال پیام"} title={sending ? "قطع پاسخ" : "ارسال پیام (Ctrl+Enter)"}>{sending ? <StopIcon /> : <SendIcon />}<span>{sending ? "توقف" : "ارسال"}</span></button></div></div>
      </form>
    </section>
    <button type="button" className={`quick-assistant-trigger fixed bottom-5 left-5 z-[65] inline-flex h-16 w-16 items-center justify-center transition hover:scale-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-primary)] ${open ? "pointer-events-none scale-90 opacity-0" : ""}`} onClick={show} aria-label="باز کردن چت سریع دستیار"><AssistantIcon className="h-16 w-16 drop-shadow-[0_10px_20px_rgba(34,55,32,0.35)]" /></button>
  </div>;
}
