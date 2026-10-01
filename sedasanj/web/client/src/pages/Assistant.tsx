import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, refreshSession, request, tokens } from "../api";
import ConversationBubble from "../components/ConversationBubble";
import { ErrorBox, Loading } from "../components/Widgets";
import type { ChatConversation, ChatMessage } from "../types";

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="h-4 w-4">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v5M14 11v5" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="h-4 w-4">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

function ArchiveIcon({ restore = false }: { restore?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
      <path d="M4 7h16v13H4Z" />
      <path d="M3 3h18v4H3Z" />
      <path d="M9 11h6" />
      {restore ? <path d="m9 16-3-3 3-3M6 13h6" /> : null}
    </svg>
  );
}

function PrivateChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-5 w-5">
      <path d="M8 11V8a4 4 0 0 1 8 0v3" />
      <path d="M5 11h14v10H5Z" />
      <path d="M12 15v2" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="h-5 w-5">
      <path d="m22 2-7 20-4-9-9-4Z" />
      <path d="M22 2 11 13" />
    </svg>
  );
}

function ChatIcon({ active, className = "h-5 w-5" }: { active: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`${className} shrink-0 ${active ? "text-[#4B6E48]" : "text-[#898989] transition group-hover:text-[#4B6E48]"}`}>
      <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z" />
      <path d="M8 9h8M8 13h5" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="h-5 w-5">
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function MenuIcon({ close = false }: { close?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" className="h-5 w-5">
      {close ? <><path d="m18 6-12 12" /><path d="m6 6 12 12" /></> : <><path d="M4 6h16" /><path d="M4 12h16" /><path d="M4 18h16" /></>}
    </svg>
  );
}

function TypingIndicator() {
  return (
    <div className="flex h-8 items-center px-1" role="status" aria-live="polite">
      <span className="assistant-thinking-text">در حال فکر کردن و دریافت نتیجه ...</span>
    </div>
  );
}

export default function Assistant() {
  const [search] = useSearchParams();
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [conversation, setConversation] = useState<ChatConversation | null>(null);
  const [ephemeral, setEphemeral] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [conversationsOpen, setConversationsOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  function resizeInput() {
    const input = inputRef.current;
    if (!input) return;
    const maxHeight = 96;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, maxHeight)}px`;
    input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
  }

  async function loadMessages(item: ChatConversation) {
    try {
      setError(null);
      const rows = await request<ChatMessage[]>(`/v1/assistant/conversations/${item.id}/messages`);
      setConversation(item);
      setEphemeral(false);
      setMessages(rows);
      setConversationsOpen(false);
    } catch (err) {
      setError((err as Error).message);
    }
  }
  async function create(callId: string | null = null) {
    const item = await request<ChatConversation>("/v1/assistant/conversations", { method: "POST", body: { call_id: callId } });
    setConversations((current) => [item, ...current]);
    setConversation(item);
    setEphemeral(false);
    setMessages([]);
    setConversationsOpen(false);
    return item;
  }
  function createEphemeral() {
    setConversation(null);
    setEphemeral(true);
    setMessages([]);
    setEditingId(null);
    setConversationsOpen(false);
    setError(null);
  }
  async function remove(item: ChatConversation) {
    try {
      setError(null);
      await request(`/v1/assistant/conversations/${item.id}`, { method: "DELETE" });
      const remaining = conversations.filter((current) => current.id !== item.id);
      setConversations(remaining);
      if (conversation?.id === item.id) {
        const next = remaining.find((current) => !current.archived_at);
        if (next) await loadMessages(next);
        else createEphemeral();
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }
  async function setArchived(item: ChatConversation, archived: boolean) {
    try {
      setError(null);
      const updated = await request<ChatConversation>(`/v1/assistant/conversations/${item.id}`, { method: "PATCH", body: { archived } });
      setConversations((current) => current.map((currentItem) => currentItem.id === updated.id ? updated : currentItem));
      if (conversation?.id === item.id && archived) {
        const next = conversations.find((current) => current.id !== item.id && !current.archived_at);
        if (next) await loadMessages(next);
        else createEphemeral();
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }
  async function rename(item: ChatConversation) {
    const nextTitle = title.trim();
    if (!nextTitle) return;
    try {
      setError(null);
      const updated = await request<ChatConversation>(`/v1/assistant/conversations/${item.id}`, { method: "PATCH", body: { title: nextTitle } });
      setConversations((current) => current.map((currentItem) => currentItem.id === updated.id ? updated : currentItem));
      setConversation((current) => current?.id === updated.id ? updated : current);
      setEditingId(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }
  useEffect(() => {
    void (async () => {
      try {
        const rows = await request<ChatConversation[]>("/v1/assistant/conversations");
        setConversations(rows);
        const callId = search.get("call_id");
        if (callId) await create(callId);
        else {
          const active = rows.find((item) => !item.archived_at);
          if (active) await loadMessages(active);
          else await create();
        }
      } catch (err) { setError((err as Error).message); }
      finally { setLoading(false); }
    })();
  }, []);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);
  useEffect(() => {
    if (!conversationsOpen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConversationsOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [conversationsOpen]);

  async function streamReply(conversationId: string | null, content: string, draftId: string, history: ChatMessage[]): Promise<ChatMessage> {
    const url = conversationId ? `/v1/assistant/conversations/${conversationId}/messages/stream` : "/v1/assistant/ephemeral/messages/stream";
    const body = conversationId
      ? { content }
      : { content, history: history.slice(-24).map((item) => ({ role: item.role, content: item.content.slice(0, 1500) })) };
    const makeRequest = () => fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(tokens.access() ? { Authorization: `Bearer ${tokens.access()}` } : {}) },
      body: JSON.stringify(body),
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
    let pendingText = "";
    let renderedText = "";
    let typingTimer: number | null = null;
    let resolveTyping: (() => void) | null = null;
    const finishTyping = () => {
      if (!resolveTyping) return;
      const resolve = resolveTyping;
      resolveTyping = null;
      resolve();
    };
    const renderTypingBatch = () => {
      typingTimer = null;
      const characters = Array.from(pendingText);
      const batch = characters.splice(0, 3).join("");
      pendingText = characters.join("");
      if (batch) {
        renderedText += batch;
        setMessages((current) => current.map((item) => item.id === draftId ? { ...item, content: renderedText } : item));
      }
      if (pendingText) typingTimer = window.setTimeout(renderTypingBatch, 14);
      else finishTyping();
    };
    const scheduleTyping = () => {
      if (typingTimer === null && pendingText) typingTimer = window.setTimeout(renderTypingBatch, 14);
    };
    const waitForTyping = () => {
      if (!pendingText && typingTimer === null) return Promise.resolve();
      return new Promise<void>((resolve) => { resolveTyping = resolve; });
    };
    const handleEvent = (frame: string) => {
      const event = /^event: (.+)$/m.exec(frame)?.[1];
      const data = /^data: (.+)$/m.exec(frame)?.[1];
      if (!event || !data) return;
      const payload = JSON.parse(data) as { content?: string; message?: ChatMessage };
      const content = payload.content;
      if (event === "delta" && content) {
        pendingText += content;
        scheduleTyping();
      }
      if (event === "replace" && content) {
        if (typingTimer !== null) window.clearTimeout(typingTimer);
        typingTimer = null;
        pendingText = "";
        renderedText = content;
        setMessages((current) => current.map((item) => item.id === draftId ? { ...item, content } : item));
        finishTyping();
      }
      if (event === "done" && payload.message) completed = payload.message;
    };
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      frames.forEach(handleEvent);
      if (done) break;
    }
    if (!completed) throw new Error("پاسخ دستیار کامل نشد.");
    await waitForTyping();
    setMessages((current) => current.map((item) => item.id === draftId ? completed as ChatMessage : item));
    return completed as ChatMessage;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || sending) return;
    try {
      setSending(true); setError(null);
      const active = ephemeral ? null : conversation ?? await create();
      const history = messages.filter((item) => item.status !== "running");
      const optimistic: ChatMessage = { id: `draft-${Date.now()}`, role: "user", content: text.trim(), status: "succeeded", model: null, sources: null, created_at: new Date().toISOString() };
      const draftReply: ChatMessage = { id: `draft-reply-${Date.now()}`, role: "assistant", content: "", status: "running", model: null, sources: null, created_at: new Date().toISOString() };
      setMessages((current) => [...current, optimistic, draftReply]); setText("");
      requestAnimationFrame(resizeInput);
      const reply = await streamReply(active?.id ?? null, optimistic.content, draftReply.id, history);
      setMessages((current) => current.map((item) => item.id === optimistic.id ? optimistic : item));
      if (active) setConversations((current) => current.map((item) => item.id === active.id ? { ...item, title: item.title || optimistic.content, updated_at: reply.created_at } : item));
    } catch (err) { setError((err as Error).message); }
    finally { setSending(false); }
  }
  function renderConversation(item: ChatConversation) {
    const isActive = conversation?.id === item.id;
    const archived = Boolean(item.archived_at);
    return <div key={item.id} className={`assistant-sidebar-item group relative w-full transition-colors duration-200 ${isActive ? "bg-[#F2F0EF] font-bold text-[#4B6E48]" : "text-[#4B6E48]"}`}>
      {editingId === item.id ? <form className="flex min-h-11 w-full items-center gap-1 p-1.5" onSubmit={(event) => { event.preventDefault(); void rename(item); }}><input autoFocus className="min-w-0 flex-1 border border-[#B2AC88] bg-[#F2F0EF] px-2 py-1 text-sm text-[#4B6E48] outline-none" value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setEditingId(null); }} aria-label="نام گفتگو" /><button type="submit" className="px-2 py-1 text-xs font-bold text-[#4B6E48] hover:bg-[#B2AC88] hover:text-white">ذخیره</button></form> : <button type="button" className="flex min-h-11 w-full items-center gap-3 px-3 py-2.5 pl-28 text-right text-sm" onClick={() => void loadMessages(item)}><ChatIcon active={isActive} /><span className="truncate">{item.title || "گفتگوی جدید"}</span>{isActive && <span className="mr-auto h-1.5 w-1.5 shrink-0 bg-[#4B6E48]" />}</button>}
      {editingId !== item.id && <div className={`absolute inset-y-0 left-1 flex items-center transition ${isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"}`}><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-[#898989] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" aria-label="ویرایش گفتگو" title="ویرایش گفتگو" onClick={() => { setTitle(item.title || ""); setEditingId(item.id); }}><EditIcon /></button><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-[#898989] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" aria-label={archived ? "بازیابی گفتگو" : "آرشیو گفتگو"} title={archived ? "بازیابی گفتگو" : "آرشیو گفتگو"} onClick={() => void setArchived(item, !archived)}><ArchiveIcon restore={archived} /></button><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-rose-600 transition hover:bg-rose-50" aria-label="حذف گفتگو" title="حذف گفتگو" onClick={() => void remove(item)}><TrashIcon /></button></div>}
    </div>;
  }
  if (loading) return <Loading />;
  return <div className="grid min-h-[calc(100vh-10rem)] items-start lg:min-h-[calc(100vh-4rem)] lg:grid-cols-[18rem_1fr] lg:border lg:border-[#B2AC88]" dir="rtl">
    <button type="button" className="flex w-full items-center justify-between border border-[#B2AC88] bg-[#F2F0EF] px-4 py-3 text-[#4B6E48] lg:hidden" onClick={() => setConversationsOpen(true)} aria-expanded={conversationsOpen} aria-controls="assistant-conversations-menu">
      <span className="min-w-0 truncate text-sm font-bold">{ephemeral ? "چت موقت" : conversation?.title || "گفتگوی جدید"}</span>
      <span className="flex shrink-0 items-center gap-2 text-xs"><MenuIcon /> گفتگوها</span>
    </button>
    <button type="button" className={`fixed inset-0 z-40 bg-slate-950/45 backdrop-blur-sm transition-opacity lg:hidden ${conversationsOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"}`} onClick={() => setConversationsOpen(false)} aria-label="بستن فهرست گفتگوها" tabIndex={conversationsOpen ? 0 : -1} />
    <aside id="assistant-conversations-menu" className={`assistant-sidebar fixed inset-y-0 right-0 z-50 flex w-[min(88vw,19rem)] flex-col overflow-hidden border-0 text-white shadow-2xl transition-transform duration-300 ease-out lg:sticky lg:top-8 lg:z-auto lg:h-[calc(100vh-4rem)] lg:w-auto lg:translate-x-0 lg:border-l lg:border-[#B2AC88] lg:shadow-none ${conversationsOpen ? "translate-x-0" : "translate-x-full"}`} role="dialog" aria-modal={conversationsOpen ? "true" : undefined} aria-label="فهرست گفتگوها">
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-[#B2AC88] px-4 lg:hidden">
        <span className="text-sm font-bold text-[#4B6E48]">گفتگوها</span>
        <button type="button" className="inline-flex h-10 w-10 items-center justify-center text-[#4B6E48] transition hover:bg-[#F2F0EF]" onClick={() => setConversationsOpen(false)} aria-label="بستن فهرست گفتگوها"><MenuIcon close /></button>
      </div>
      <nav className="sidebar-scroll flex-1 overflow-y-auto px-3 pb-24 pt-5" aria-label="فهرست گفتگوها">
        <div className="mb-5">
          <p className="mb-2 px-3 text-[11px] font-medium text-[#898989]">گفتگوها</p>
          <div className="space-y-1">
          {conversations.filter((item) => !item.archived_at).map(renderConversation)}
          </div>
        </div>
        {conversations.some((item) => item.archived_at) ? <div className="mb-5"><p className="mb-2 px-3 text-[11px] font-medium text-[#898989]">آرشیو‌شده‌ها</p><div className="space-y-1">{conversations.filter((item) => item.archived_at).map(renderConversation)}</div></div> : null}
      </nav>
      <div className="absolute bottom-5 left-5 z-10 flex gap-2"><button type="button" className="inline-flex h-14 w-14 items-center justify-center border border-[#4B6E48] bg-[#F2F0EF] text-[#4B6E48] shadow-[0_10px_30px_rgba(75,110,72,0.18)] transition duration-200 hover:-translate-y-0.5 hover:bg-[#B2AC88] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]" onClick={createEphemeral} aria-label="چت موقت بدون ذخیره‌سازی" title="چت موقت بدون ذخیره‌سازی"><PrivateChatIcon /></button><button type="button" className="inline-flex h-14 w-14 items-center justify-center bg-[#4B6E48] text-[#F2F0EF] shadow-[0_10px_30px_rgba(75,110,72,0.28)] transition duration-200 hover:-translate-y-0.5 hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]" onClick={() => void create()} aria-label="گفتگوی جدید" title="گفتگوی جدید">
        <PlusIcon />
      </button></div>
    </aside>
    <section className="relative flex h-[calc(100dvh-10rem)] min-h-[32rem] flex-col overflow-hidden border border-[#B2AC88] bg-[#F2F0EF] lg:h-[calc(100dvh-4rem)] lg:border-0">
      <div className="sidebar-scroll flex-1 space-y-5 overflow-y-auto p-4 md:p-7">
        {ephemeral ? <div className="mx-auto flex max-w-xl items-center gap-2 border border-[#B2AC88] bg-white px-3 py-2 text-xs text-[#4B6E48]" role="status"><PrivateChatIcon /><span>این چت ذخیره نمی‌شود و با بستن یا ترک صفحه از بین می‌رود.</span></div> : null}
        {messages.length === 0 ? <div className="mx-auto max-w-lg pt-20 text-center text-[#898989]"><div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center border border-[#B2AC88] bg-[#F2F0EF]">{ephemeral ? <PrivateChatIcon /> : <ChatIcon active className="h-9 w-9" />}</div><h1 className="mb-3 text-xl font-bold text-[#4B6E48]">{ephemeral ? "چت موقت" : "دستیار تماس‌ها"}</h1><p>درباره تماس‌ها، متن مکالمات، تحلیل‌ها و عملکرد اپراتورها سؤال کنید.</p></div> : null}
        {messages.map((message) => {
          const user = message.role === "user";
          return <ConversationBubble key={message.id} side={user ? "user" : "assistant"}>
              {message.status === "running" && !message.content ? <TypingIndicator /> : <p className="whitespace-pre-wrap">{message.content}</p>}
              {message.sources?.length ? <div className="mt-3 border-t border-[#B2AC88] pt-2 text-xs text-[#898989]">{message.sources.map((source) => <Link className="ml-3 text-[#4B6E48]" key={source.call_id} to={`/calls/${source.call_id}`}>تماس {fmt.date(source.started_at)}</Link>)}</div> : null}
          </ConversationBubble>;
        })}
        <div ref={endRef} />
      </div>
      <form className="flex shrink-0 items-start gap-2 border-t border-[#B2AC88] bg-white p-3" onSubmit={submit}><div className="min-w-0 flex-1"><textarea ref={inputRef} rows={1} className="input h-12 min-h-12 resize-none overflow-y-hidden border-0 bg-[#F2F0EF] py-3 text-slate-900 focus:!border-[#4B6E48]" value={text} onChange={(event) => { setText(event.target.value); requestAnimationFrame(resizeInput); }} onKeyDown={(event) => { if (event.ctrlKey && event.key === "Enter") { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="سؤال خود را بنویسید…" /><p className="mt-1 text-[11px] text-[#898989]">برای ارسال، <kbd className="font-sans text-[#4B6E48]" dir="ltr">Ctrl + Enter</kbd> را بزنید</p></div><button type="submit" className="inline-flex min-h-12 w-12 shrink-0 self-stretch items-center justify-center bg-[#4B6E48] text-[#F2F0EF] transition hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:bg-[#898989] disabled:opacity-60" aria-label="ارسال پیام" title="ارسال پیام" disabled={sending || !text.trim()}><SendIcon /></button></form>
    </section>
    <ErrorBox message={error} />
  </div>;
}
