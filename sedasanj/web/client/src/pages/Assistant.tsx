import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fmt, refreshSession, request, tokens } from "../api";
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

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" className="h-5 w-5">
      <path d="m22 2-7 20-4-9-9-4Z" />
      <path d="M22 2 11 13" />
    </svg>
  );
}

function ChatIcon({ active }: { active: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`h-5 w-5 shrink-0 ${active ? "text-[#4B6E48]" : "text-[#898989] transition group-hover:text-[#4B6E48]"}`}>
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

export default function Assistant() {
  const [search] = useSearchParams();
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [conversation, setConversation] = useState<ChatConversation | null>(null);
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
    setMessages([]);
    setConversationsOpen(false);
    return item;
  }
  async function remove(item: ChatConversation) {
    try {
      setError(null);
      await request(`/v1/assistant/conversations/${item.id}`, { method: "DELETE" });
      const remaining = conversations.filter((current) => current.id !== item.id);
      setConversations(remaining);
      if (conversation?.id === item.id) {
        if (remaining[0]) await loadMessages(remaining[0]);
        else await create();
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
        else if (rows[0]) await loadMessages(rows[0]);
        else await create();
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

  async function streamReply(conversationId: string, content: string, draftId: string): Promise<ChatMessage> {
    const makeRequest = () => fetch(`/v1/assistant/conversations/${conversationId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(tokens.access() ? { Authorization: `Bearer ${tokens.access()}` } : {}) },
      body: JSON.stringify({ content }),
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
    const handleEvent = (frame: string) => {
      const event = /^event: (.+)$/m.exec(frame)?.[1];
      const data = /^data: (.+)$/m.exec(frame)?.[1];
      if (!event || !data) return;
      const payload = JSON.parse(data) as { content?: string; message?: ChatMessage };
      const content = payload.content;
      if (event === "delta" && content) {
        setMessages((current) => current.map((item) => item.id === draftId ? { ...item, content: item.content + content } : item));
      }
      if (event === "replace" && content) {
        setMessages((current) => current.map((item) => item.id === draftId ? { ...item, content } : item));
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
    setMessages((current) => current.map((item) => item.id === draftId ? completed as ChatMessage : item));
    return completed as ChatMessage;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || sending) return;
    try {
      setSending(true); setError(null);
      const active = conversation ?? await create();
      const optimistic: ChatMessage = { id: `draft-${Date.now()}`, role: "user", content: text.trim(), status: "succeeded", model: null, sources: null, created_at: new Date().toISOString() };
      const draftReply: ChatMessage = { id: `draft-reply-${Date.now()}`, role: "assistant", content: "", status: "running", model: null, sources: null, created_at: new Date().toISOString() };
      setMessages((current) => [...current, optimistic, draftReply]); setText("");
      requestAnimationFrame(resizeInput);
      const reply = await streamReply(active.id, optimistic.content, draftReply.id);
      setMessages((current) => current.map((item) => item.id === optimistic.id ? optimistic : item));
      setConversations((current) => current.map((item) => item.id === active.id ? { ...item, title: item.title || optimistic.content, updated_at: reply.created_at } : item));
    } catch (err) { setError((err as Error).message); }
    finally { setSending(false); }
  }
  if (loading) return <Loading />;
  return <div className="grid min-h-[calc(100vh-10rem)] items-start gap-4 lg:min-h-[calc(100vh-4rem)] lg:grid-cols-[18rem_1fr]" dir="rtl">
    <button type="button" className="flex w-full items-center justify-between border border-[#B2AC88] bg-[#F2F0EF] px-4 py-3 text-[#4B6E48] lg:hidden" onClick={() => setConversationsOpen(true)} aria-expanded={conversationsOpen} aria-controls="assistant-conversations-menu">
      <span className="min-w-0 truncate text-sm font-bold">{conversation?.title || "گفتگوی جدید"}</span>
      <span className="flex shrink-0 items-center gap-2 text-xs"><MenuIcon /> گفتگوها</span>
    </button>
    <button type="button" className={`fixed inset-0 z-40 bg-slate-950/45 backdrop-blur-sm transition-opacity lg:hidden ${conversationsOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"}`} onClick={() => setConversationsOpen(false)} aria-label="بستن فهرست گفتگوها" tabIndex={conversationsOpen ? 0 : -1} />
    <aside id="assistant-conversations-menu" className={`assistant-sidebar fixed inset-y-0 right-0 z-50 flex w-[min(88vw,19rem)] flex-col overflow-hidden text-white shadow-2xl transition-transform duration-300 ease-out lg:sticky lg:top-8 lg:z-auto lg:h-[calc(100vh-4rem)] lg:w-auto lg:translate-x-0 lg:shadow-none ${conversationsOpen ? "translate-x-0" : "translate-x-full"}`} role="dialog" aria-modal={conversationsOpen ? "true" : undefined} aria-label="فهرست گفتگوها">
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-[#B2AC88] px-4 lg:hidden">
        <span className="text-sm font-bold text-[#4B6E48]">گفتگوها</span>
        <button type="button" className="inline-flex h-10 w-10 items-center justify-center text-[#4B6E48] transition hover:bg-[#F2F0EF]" onClick={() => setConversationsOpen(false)} aria-label="بستن فهرست گفتگوها"><MenuIcon close /></button>
      </div>
      <nav className="sidebar-scroll flex-1 overflow-y-auto px-3 pb-24 pt-5" aria-label="فهرست گفتگوها">
        <div className="mb-5">
          <p className="mb-2 px-3 text-[11px] font-medium text-[#898989]">گفتگوها</p>
          <div className="space-y-1">
          {conversations.map((item) => {
            const isActive = conversation?.id === item.id;
            return <div key={item.id} className={`assistant-sidebar-item group relative w-full transition-colors duration-200 ${isActive ? "bg-[#F2F0EF] font-bold text-[#4B6E48]" : "text-[#4B6E48]"}`}>
              {editingId === item.id ? <form className="flex min-h-11 w-full items-center gap-1 p-1.5" onSubmit={(event) => { event.preventDefault(); void rename(item); }}><input autoFocus className="min-w-0 flex-1 border border-[#B2AC88] bg-[#F2F0EF] px-2 py-1 text-sm text-[#4B6E48] outline-none" value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setEditingId(null); }} aria-label="نام گفتگو" /><button type="submit" className="px-2 py-1 text-xs font-bold text-[#4B6E48] hover:bg-[#B2AC88] hover:text-white">ذخیره</button></form> : <button type="button" className="flex min-h-11 w-full items-center gap-3 px-3 py-2.5 pl-20 text-right text-sm" onClick={() => void loadMessages(item)}><ChatIcon active={isActive} /><span className="truncate">{item.title || "گفتگوی جدید"}</span>{isActive && <span className="mr-auto h-1.5 w-1.5 shrink-0 bg-[#4B6E48]" />}</button>}
              {editingId !== item.id && <div className={`absolute inset-y-0 left-1 flex items-center transition ${isActive ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"}`}><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-[#898989] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" aria-label="ویرایش گفتگو" title="ویرایش گفتگو" onClick={() => { setTitle(item.title || ""); setEditingId(item.id); }}><EditIcon /></button><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-rose-600 transition hover:bg-rose-50" aria-label="حذف گفتگو" title="حذف گفتگو" onClick={() => void remove(item)}><TrashIcon /></button></div>}
            </div>;
          })}
          </div>
        </div>
      </nav>
      <button type="button" className="assistant-new-chat-button absolute bottom-5 left-5 z-10 inline-flex h-14 w-14 items-center justify-center bg-[#4B6E48] text-[#F2F0EF] shadow-[0_10px_30px_rgba(75,110,72,0.28)] transition duration-200 hover:-translate-y-0.5 hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]" onClick={() => void create()} aria-label="گفتگوی جدید" title="گفتگوی جدید">
        <PlusIcon />
      </button>
    </aside>
    <section className="relative min-h-[70vh] rounded-2xl border border-slate-200 bg-slate-50 pb-28 lg:min-h-[calc(100vh-4rem)]">
      <div className="space-y-5 p-4 md:p-7">{messages.length === 0 ? <div className="mx-auto max-w-lg pt-20 text-center text-slate-500"><h1 className="mb-3 text-xl font-bold text-slate-800">دستیار تماس‌ها</h1><p>درباره تماس‌ها، متن مکالمات، تحلیل‌ها و عملکرد اپراتورها سؤال کنید.</p></div> : null}{messages.map((message) => <div key={message.id} className={`w-fit max-w-[85%] break-words rounded-2xl px-4 py-3 leading-8 shadow-sm ${message.role === "user" ? "ml-auto bg-brand-600 text-white" : "mr-auto bg-white text-slate-800"}`}><p className="whitespace-pre-wrap">{message.content || (message.status === "running" ? "در حال نوشتن…" : "")}</p>{message.sources?.length ? <div className="mt-3 border-t border-slate-200 pt-2 text-xs text-slate-500">{message.sources.map((source) => <Link className="ml-3 text-brand-700" key={source.call_id} to={`/calls/${source.call_id}`}>تماس {fmt.date(source.started_at)}</Link>)}</div> : null}</div>)}<div ref={endRef} /></div>
      <form className="absolute inset-x-3 bottom-3 mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-lg" onSubmit={submit}><textarea ref={inputRef} rows={1} className="input h-12 min-h-12 flex-1 resize-none overflow-y-hidden border-0 py-3" value={text} onChange={(event) => { setText(event.target.value); requestAnimationFrame(resizeInput); }} placeholder="سؤال خود را بنویسید…" /><button type="submit" className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50" aria-label="ارسال پیام" title="ارسال پیام" disabled={sending || !text.trim()}><SendIcon /></button></form>
    </section>
    <ErrorBox message={error} />
  </div>;
}
