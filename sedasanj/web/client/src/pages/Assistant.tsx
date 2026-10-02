import { FormEvent, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt, INTENT_LABELS, refreshSession, request, STATUS_LABELS, tokens } from "../api";
import ConversationBubble from "../components/ConversationBubble";
import ConfirmDialog from "../components/ConfirmDialog";
import MarkdownMessage from "../components/MarkdownMessage";
import { ErrorBox, Loading, SentimentBadge, StatusBadge } from "../components/Widgets";
import type { AssistantCallSource, AssistantChart, AssistantToolRun, ChatConversation, ChatMessage } from "../types";
import { downloadTextFile, safeDownloadName } from "../utils/download";

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

function PinIcon({ pinned = false }: { pinned?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-4 w-4">
      <path d="M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6Z" fill={pinned ? "currentColor" : "none"} />
      <path d="M12 14v7" />
    </svg>
  );
}

function TemporaryChatIcon({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
      <path d="M20 15a3 3 0 0 1-3 3H9l-5 3v-6a3 3 0 0 1-1-2.24V7a3 3 0 0 1 3-3h7" />
      <circle cx="17" cy="7" r="4" />
      <path d="M17 5v2.25l1.5 1" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-5 w-5">
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 21h14" />
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

function IconTooltip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 hidden w-max -translate-x-1/2 border border-[#B2AC88] bg-[#4B6E48] px-2.5 py-1.5 text-[11px] font-medium text-[#F2F0EF] shadow-lg group-hover:block group-focus-within:block" role="tooltip">
        {label}
      </span>
    </span>
  );
}

function TypingIndicator({ label = "در حال فکر کردن و دریافت نتیجه ..." }: { label?: string }) {
  return (
    <div className="flex h-8 items-center px-1" role="status" aria-live="polite">
      <span className="assistant-thinking-text">{label}</span>
    </div>
  );
}

function ToolTimeline({ runs, active }: { runs: AssistantToolRun[]; active: boolean }) {
  const [open, setOpen] = useState(active);
  useEffect(() => { if (active) setOpen(true); }, [active]);
  if (!runs.length) return null;
  const succeeded = runs.filter((run) => run.status === "succeeded").length;
  return <div className="mb-3 border border-[#B2AC88] bg-white/70 text-xs text-[#4B6E48]" aria-live="polite">
    <button type="button" className="flex w-full items-center justify-between gap-3 px-3 py-2 text-right font-bold" onClick={() => setOpen((current) => !current)} aria-expanded={open}>
      <span>{active ? "در حال استفاده از ابزارها" : `${fmt.int(succeeded)} ابزار استفاده شد`}</span>
      <span aria-hidden="true">{open ? "−" : "+"}</span>
    </button>
    {open ? <ol className="space-y-2 border-t border-[#B2AC88] px-3 py-2">
      {runs.map((run) => <li key={run.tool_call_id} className="flex items-start gap-2">
        <span className={`mt-0.5 inline-block h-2.5 w-2.5 shrink-0 ${run.status === "running" ? "animate-pulse bg-[#B2AC88]" : run.status === "succeeded" ? "bg-[#4B6E48]" : "bg-rose-600"}`} />
        <span className="min-w-0"><span className="font-bold">{run.title}</span>{run.summary ? <span className="mr-2 text-[#898989]">{run.summary}</span> : run.status === "failed" ? <span className="mr-2 text-rose-700">اجرای ابزار ناموفق بود</span> : <span className="mr-2 text-[#898989]">در حال اجرا…</span>}</span>
      </li>)}
    </ol> : null}
  </div>;
}

const assistantChartColors = ["#4B6E48", "#B2AC88", "#7A8B73", "#898989", "#D8D3B9"];

function AssistantCharts({ charts }: { charts: AssistantChart[] }) {
  const visible = charts.filter((chart) => chart.data.some((item) => Number.isFinite(item.value)));
  if (!visible.length) return null;
  return <section className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2" aria-label="نمودارهای آماری پاسخ">
    {visible.map((chart) => <article key={chart.id} className={`min-w-0 border border-[#B2AC88] bg-white p-3 ${chart.size === "full" ? "md:col-span-2" : ""}`}>
      <h3 className="mb-3 text-sm font-bold text-[#4B6E48]">{chart.title}</h3>
      <div className="h-64 w-full" dir="ltr">
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "donut" ? <PieChart>
            <Pie data={chart.data.map((item) => ({ ...item, label: STATUS_LABELS[item.label] || item.label }))} dataKey="value" nameKey="label" innerRadius={54} outerRadius={82} paddingAngle={2}>
              {chart.data.map((item, index) => <Cell key={`${chart.id}-${item.label}`} fill={assistantChartColors[index % assistantChartColors.length]} />)}
            </Pie>
            <Tooltip formatter={(value) => [fmt.int(Number(value)), chart.value_label]} />
            <Legend wrapperStyle={{ direction: "rtl", fontSize: 11 }} />
          </PieChart> : <BarChart data={chart.data} margin={{ top: 8, right: 8, left: 8, bottom: 32 }}>
            <CartesianGrid stroke="#E3E0D4" strokeDasharray="3 3" />
            <XAxis dataKey="label" interval={0} angle={-18} textAnchor="end" height={58} tick={{ fontSize: 10 }} />
            <YAxis orientation="right" allowDecimals={false} tickFormatter={(value) => fmt.int(Number(value))} tick={{ fontSize: 10 }} />
            <Tooltip formatter={(value) => [fmt.decimal(Number(value)), chart.value_label]} />
            <Bar dataKey="value" name={chart.value_label} fill="#4B6E48" />
          </BarChart>}
        </ResponsiveContainer>
      </div>
    </article>)}
  </section>;
}

function PhoneIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="h-5 w-5"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.12.9.33 1.78.62 2.63a2 2 0 0 1-.45 2.11L8 9.73a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.85.29 1.73.5 2.63.62A2 2 0 0 1 22 16.92Z" /></svg>;
}

function ChevronIcon({ open }: { open: boolean }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}><path d="m6 9 6 6 6-6" /></svg>;
}

function CallSources({ sources, expandedCallId, onToggle }: { sources: AssistantCallSource[]; expandedCallId: string | null; onToggle: (callId: string) => void }) {
  return <section className="mt-4 border-t border-[#B2AC88] pt-3" aria-label="تماس‌های استفاده‌شده در پاسخ">
    <div className="mb-3 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 text-[#4B6E48]"><PhoneIcon /><h3 className="text-sm font-bold">تماس‌های بررسی‌شده</h3></div>
      <span className="border border-[#B2AC88] bg-[#F2F0EF] px-2 py-1 text-[11px] font-bold text-[#4B6E48]">{fmt.int(sources.length)} تماس</span>
    </div>
    <div className="max-h-[30rem] overflow-auto border border-[#B2AC88] bg-white">
      <table className="w-full min-w-[42rem] border-collapse text-xs">
        <thead className="sticky top-0 z-10 bg-[#F2F0EF] text-[#4B6E48]">
          <tr className="border-b border-[#B2AC88]">
            <th className="w-10 px-3 py-2 text-right" aria-label="نمایش جزئیات" />
            <th className="px-3 py-2 text-right">تاریخ و زمان</th>
            <th className="px-3 py-2 text-right">شماره تماس</th>
            <th className="px-3 py-2 text-right">جهت</th>
            <th className="px-3 py-2 text-right">مدت</th>
            <th className="px-3 py-2 text-right">وضعیت</th>
          </tr>
        </thead>
        {sources.map((source) => {
          const open = expandedCallId === source.call_id;
          const primaryNumber = source.direction === "outbound" ? source.dialed_number : source.caller_number;
          const secondaryNumber = source.direction === "outbound" ? source.caller_number : source.dialed_number;
          const detailsId = `assistant-call-source-${source.call_id}`;
          return <tbody key={source.call_id} className="border-b border-[#E3E0D4] last:border-b-0">
            <tr className={`transition hover:bg-[#F2F0EF] ${open ? "bg-[#F2F0EF]" : "bg-white"}`}>
              <td className="p-0">
                <button type="button" className="flex h-11 w-full items-center justify-center text-[#4B6E48]" onClick={() => onToggle(source.call_id)} aria-expanded={open} aria-controls={detailsId} aria-label={open ? "بستن جزئیات تماس" : "نمایش جزئیات تماس"}><ChevronIcon open={open} /></button>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-[#555555]">{source.started_at ? fmt.dateTime(source.started_at) : "زمان نامشخص"}</td>
              <td className="whitespace-nowrap px-3 py-2 font-bold text-[#4B6E48]" dir="ltr">{primaryNumber ? fmt.digits(primaryNumber) : "شماره نامشخص"}</td>
              <td className="px-3 py-2">{source.direction === "inbound" ? "ورودی" : source.direction === "outbound" ? "خروجی" : source.direction || "—"}</td>
              <td className="whitespace-nowrap px-3 py-2">{source.duration_ms == null ? "—" : fmt.duration(source.duration_ms)}</td>
              <td className="px-3 py-2">{source.status ? <StatusBadge status={source.status} /> : "—"}</td>
            </tr>
            {open ? <tr id={detailsId}>
              <td colSpan={6} className="bg-[#FCFBF8] px-4 py-4">
                <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto]">
                  <div className="min-w-0">
                    <dl className="mb-3 grid grid-cols-2 gap-3 text-[11px] sm:grid-cols-3">
                      <div><dt className="text-[#898989]">شماره مقابل</dt><dd className="mt-1 font-bold" dir="ltr">{secondaryNumber ? fmt.digits(secondaryNumber) : "—"}</dd></div>
                      <div><dt className="text-[#898989]">داخلی اپراتور</dt><dd className="mt-1 font-bold" dir="ltr">{source.agent_extension ? fmt.digits(source.agent_extension) : "—"}</dd></div>
                      <div><dt className="text-[#898989]">شناسه تماس</dt><dd className="mt-1 truncate font-mono text-[10px]" dir="ltr" title={source.call_id}>{source.call_id}</dd></div>
                    </dl>
                    <div className="mb-3 flex flex-wrap items-center gap-2">
                      {source.intent ? <span className="border border-[#D8D3B9] bg-[#F2F0EF] px-2 py-1 text-[11px] text-[#4B6E48]">{INTENT_LABELS[source.intent] ?? source.intent}</span> : null}
                      {source.sentiment ? <SentimentBadge sentiment={source.sentiment} /> : null}
                    </div>
                    <p className="text-xs leading-6 text-[#555555]">{source.summary || "خلاصه‌ای برای این تماس ثبت نشده است."}</p>
                  </div>
                  <Link className="inline-flex h-10 items-center justify-center self-end border border-[#4B6E48] px-4 text-xs font-bold text-[#4B6E48] transition hover:bg-[#4B6E48] hover:text-white" to={`/calls/${source.call_id}`}>مشاهده تماس</Link>
                </div>
              </td>
            </tr> : null}
          </tbody>;
        })}
      </table>
    </div>
  </section>;
}

const promptGuides = [
  "برای ارسال، Ctrl + Enter را بزنید",
  "هوش مصنوعی می‌تواند خطا کند",
  "برای منشن کردن اپراتور خاص یا زمان خاص و ... از @ استفاده کنید",
];

function TypingPromptGuide() {
  const [guideIndex, setGuideIndex] = useState(0);
  const [characterCount, setCharacterCount] = useState(0);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const guide = promptGuides[guideIndex];
    const finishedTyping = characterCount === Array.from(guide).length;
    const finishedDeleting = characterCount === 0;
    const delay = finishedTyping ? 2200 : deleting ? 24 : 48;
    const timer = window.setTimeout(() => {
      if (finishedTyping && !deleting) {
        setDeleting(true);
        return;
      }
      if (deleting && finishedDeleting) {
        setDeleting(false);
        setGuideIndex((current) => (current + 1) % promptGuides.length);
        return;
      }
      setCharacterCount((current) => current + (deleting ? -1 : 1));
    }, delay);
    return () => window.clearTimeout(timer);
  }, [characterCount, deleting, guideIndex]);

  return <span aria-hidden="true">{Array.from(promptGuides[guideIndex]).slice(0, characterCount).join("")}<span className="animate-pulse">|</span></span>;
}

export default function Assistant() {
  const [search, setSearch] = useSearchParams();
  const expandedCallId = search.get("source_call");
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
  const [conversationView, setConversationView] = useState<"active" | "archived">("active");
  const [confirmation, setConfirmation] = useState<{ action: "archive" | "delete"; item: ChatConversation } | null>(null);
  const [phases, setPhases] = useState<Record<string, string>>({});
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  function toggleCallSource(callId: string) {
    setSearch((current) => {
      const next = new URLSearchParams(current);
      if (next.get("source_call") === callId) next.delete("source_call");
      else next.set("source_call", callId);
      return next;
    }, { replace: true });
  }

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
    setConversationView("active");
    return item;
  }
  function createEphemeral() {
    if (ephemeral) return;
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
  async function setPinned(item: ChatConversation, pinned: boolean) {
    try {
      setError(null);
      const updated = await request<ChatConversation>(`/v1/assistant/conversations/${item.id}`, { method: "PATCH", body: { pinned } });
      setConversations((current) => current.map((currentItem) => currentItem.id === updated.id ? updated : currentItem));
      setConversation((current) => current?.id === updated.id ? updated : current);
    } catch (err) {
      setError((err as Error).message);
    }
  }
  async function confirmConversationAction() {
    if (!confirmation) return;
    const { action, item } = confirmation;
    setConfirmation(null);
    if (action === "delete") await remove(item);
    else await setArchived(item, true);
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
  useEffect(() => {
    if (!confirmation) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConfirmation(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [confirmation]);

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
      const payload = JSON.parse(data) as { content?: string; message?: ChatMessage; phase?: string; label?: string; tool_call_id?: string; name?: string; title?: string; status?: AssistantToolRun["status"]; duration_ms?: number; summary?: string; error_code?: string; charts?: AssistantChart[] };
      const content = payload.content;
      if (event === "phase" && payload.label) setPhases((current) => ({ ...current, [draftId]: payload.label as string }));
      if ((event === "tool_started" || event === "tool_completed" || event === "tool_failed") && payload.tool_call_id && payload.name && payload.title) {
        const run: AssistantToolRun = { tool_call_id: payload.tool_call_id, name: payload.name, title: payload.title, status: payload.status || (event === "tool_started" ? "running" : event === "tool_failed" ? "failed" : "succeeded"), duration_ms: payload.duration_ms ?? null, summary: payload.summary ?? null, error_code: payload.error_code ?? null, charts: payload.charts || [] };
        setMessages((current) => current.map((item) => item.id === draftId ? { ...item, tool_runs: [...(item.tool_runs || []).filter((existing) => existing.tool_call_id !== run.tool_call_id), run] } : item));
      }
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
      const optimistic: ChatMessage = { id: `draft-${Date.now()}`, role: "user", content: text.trim(), status: "succeeded", model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() };
      const draftReply: ChatMessage = { id: `draft-reply-${Date.now()}`, role: "assistant", content: "", status: "running", model: null, sources: null, tool_runs: [], created_at: new Date().toISOString() };
      setMessages((current) => [...current, optimistic, draftReply]); setText("");
      requestAnimationFrame(resizeInput);
      const reply = await streamReply(active?.id ?? null, optimistic.content, draftReply.id, history);
      setMessages((current) => current.map((item) => item.id === optimistic.id ? optimistic : item));
      if (active) setConversations((current) => current.map((item) => item.id === active.id ? { ...item, title: item.title || optimistic.content, updated_at: reply.created_at } : item));
    } catch (err) { setError((err as Error).message); }
    finally { setSending(false); }
  }
  function exportMessages() {
    const completedMessages = messages.filter((message) => message.status !== "running" && message.content.trim());
    if (!completedMessages.length) return;
    const heading = ephemeral ? "چت موقت" : conversation?.title?.trim() || "گفتگوی جدید";
    const transcript = completedMessages.map((message) => {
      const role = message.role === "user" ? "کاربر" : "دستیار";
      const timestamp = fmt.dateTime(message.created_at);
      return `${role} - ${timestamp}\n${message.content.trim()}`;
    }).join("\n\n--------------------\n\n");
    downloadTextFile(`${safeDownloadName(heading, "conversation")}.txt`, `${heading}\n\n${transcript}\n`);
  }
  function renderConversation(item: ChatConversation) {
    const isActive = conversation?.id === item.id;
    const archived = Boolean(item.archived_at);
    const pinned = Boolean(item.pinned_at);
    return <div key={item.id} className={`assistant-sidebar-item group relative w-full transition-colors duration-200 ${isActive ? "bg-[#F2F0EF] font-bold text-[#4B6E48]" : "text-[#4B6E48]"}`}>
      {editingId === item.id ? <form className="flex min-h-11 w-full items-center gap-1 p-1.5" onSubmit={(event) => { event.preventDefault(); void rename(item); }}><input autoFocus className="min-w-0 flex-1 border border-[#B2AC88] bg-[#F2F0EF] px-2 py-1 text-sm text-[#4B6E48] outline-none" value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") { setEditingId(null); setTitle(""); } }} aria-label="نام گفتگو" /><button type="button" className="px-2 py-1 text-xs font-bold text-[#898989] hover:bg-[#F2F0EF] hover:text-[#4B6E48]" onClick={() => { setEditingId(null); setTitle(""); }}>انصراف</button><button type="submit" className="px-2 py-1 text-xs font-bold text-[#4B6E48] hover:bg-[#B2AC88] hover:text-white">ذخیره</button></form> : <button type="button" className={`flex min-h-11 w-full items-center gap-3 py-2.5 pr-3 pl-3 text-right text-sm transition-[padding] ${archived ? "group-hover:pl-28 group-focus-within:pl-28" : "group-hover:pl-36 group-focus-within:pl-36"}`} onClick={() => void loadMessages(item)}><ChatIcon active={isActive} /><span className="min-w-0 flex-1 truncate">{item.title || "گفتگوی جدید"}</span></button>}
      {editingId !== item.id && <div className="pointer-events-none absolute inset-y-0 left-1 flex items-center opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-[#898989] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" aria-label="ویرایش گفتگو" title="ویرایش گفتگو" onClick={() => { setTitle(item.title || ""); setEditingId(item.id); }}><EditIcon /></button>{!archived ? <button type="button" className={`inline-flex h-8 w-8 items-center justify-center transition hover:bg-[#B2AC88] hover:text-[#4B6E48] ${pinned ? "text-[#4B6E48]" : "text-[#898989]"}`} aria-label={pinned ? "برداشتن پین گفتگو" : "پین کردن گفتگو"} title={pinned ? "برداشتن پین گفتگو" : "پین کردن گفتگو"} onClick={() => void setPinned(item, !pinned)}><PinIcon pinned={pinned} /></button> : null}<button type="button" className="inline-flex h-8 w-8 items-center justify-center text-[#898989] transition hover:bg-[#B2AC88] hover:text-[#4B6E48]" aria-label={archived ? "بازیابی گفتگو" : "آرشیو گفتگو"} title={archived ? "بازیابی گفتگو" : "آرشیو گفتگو"} onClick={() => archived ? void setArchived(item, false) : setConfirmation({ action: "archive", item })}><ArchiveIcon restore={archived} /></button><button type="button" className="inline-flex h-8 w-8 items-center justify-center text-rose-600 transition hover:bg-rose-50" aria-label="حذف گفتگو" title="حذف گفتگو" onClick={() => setConfirmation({ action: "delete", item })}><TrashIcon /></button></div>}
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
      <nav className="sidebar-scroll flex-1 overflow-y-auto px-3 pb-24 pt-3" aria-label="فهرست گفتگوها">
        <div className="mb-5 flex border border-[#B2AC88] bg-white p-1" role="tablist" aria-label="نوع گفتگوها">
          <button type="button" role="tab" aria-selected={conversationView === "active"} className={`min-h-9 flex-1 px-3 text-xs font-bold transition ${conversationView === "active" ? "bg-[#4B6E48] text-[#F2F0EF]" : "text-[#4B6E48] hover:bg-[#F2F0EF]"}`} onClick={() => setConversationView("active")}>گفتگوها</button>
          <button type="button" role="tab" aria-selected={conversationView === "archived"} className={`min-h-9 flex-1 px-3 text-xs font-bold transition ${conversationView === "archived" ? "bg-[#4B6E48] text-[#F2F0EF]" : "text-[#4B6E48] hover:bg-[#F2F0EF]"}`} onClick={() => setConversationView("archived")}>آرشیوها</button>
        </div>
        {conversationView === "active" ? <>{conversations.some((item) => item.pinned_at && !item.archived_at) ? <div className="mb-5"><p className="mb-2 px-3 text-[11px] font-medium text-[#898989]">پین‌شده‌ها</p><div className="space-y-1">{conversations.filter((item) => item.pinned_at && !item.archived_at).sort((first, second) => Date.parse(second.pinned_at || "") - Date.parse(first.pinned_at || "")).map(renderConversation)}</div></div> : null}<div className="mb-5">
          <p className="mb-2 px-3 text-[11px] font-medium text-[#898989]">گفتگوهای فعال</p>
          {conversations.some((item) => !item.archived_at && !item.pinned_at) ? <div className="space-y-1">{conversations.filter((item) => !item.archived_at && !item.pinned_at).map(renderConversation)}</div> : <p className="px-3 py-8 text-center text-xs text-[#898989]">گفتگوی فعال دیگری وجود ندارد.</p>}
        </div></> : <div className="mb-5"><p className="mb-2 px-3 text-[11px] font-medium text-[#898989]">گفتگوهای آرشیوشده</p>{conversations.some((item) => item.archived_at) ? <div className="space-y-1">{conversations.filter((item) => item.archived_at).map(renderConversation)}</div> : <p className="px-3 py-8 text-center text-xs text-[#898989]">گفتگوی آرشیوشده‌ای وجود ندارد.</p>}</div>}
      </nav>
      <button type="button" className="absolute bottom-5 left-5 z-10 inline-flex h-14 w-14 items-center justify-center bg-[#4B6E48] text-[#F2F0EF] shadow-[0_10px_30px_rgba(75,110,72,0.28)] transition duration-200 hover:-translate-y-0.5 hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48]" onClick={() => void create()} aria-label="گفتگوی جدید" title="گفتگوی جدید">
        <PlusIcon />
      </button>
    </aside>
    <section className="relative flex h-[calc(100dvh-10rem)] min-h-[32rem] flex-col overflow-hidden border border-[#B2AC88] bg-[#F2F0EF] lg:h-[calc(100dvh-4rem)] lg:border-0">
      <div className="absolute left-3 top-3 z-20 flex gap-2 md:left-4 md:top-4">
        <IconTooltip label="چت موقت بدون ذخیره‌سازی">
          <button type="button" className={`inline-flex h-11 w-11 items-center justify-center border transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] ${ephemeral ? "border-[#4B6E48] bg-[#4B6E48] text-[#F2F0EF]" : "border-[#B2AC88] bg-white text-[#4B6E48] hover:border-[#4B6E48] hover:bg-[#F2F0EF]"}`} onClick={createEphemeral} aria-label="شروع چت موقت بدون ذخیره‌سازی" aria-pressed={ephemeral}><TemporaryChatIcon /></button>
        </IconTooltip>
        <IconTooltip label="خروجی متن پیام‌ها">
          <button type="button" className="inline-flex h-11 w-11 items-center justify-center border border-[#B2AC88] bg-white text-[#4B6E48] transition hover:border-[#4B6E48] hover:bg-[#F2F0EF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:text-[#898989] disabled:opacity-50" onClick={exportMessages} aria-label="خروجی متن پیام‌ها" disabled={!messages.some((message) => message.status !== "running" && message.content.trim())}><DownloadIcon /></button>
        </IconTooltip>
      </div>
      <div className="sidebar-scroll flex-1 space-y-5 overflow-y-auto p-4 md:p-7">
        {ephemeral ? <div className="mx-auto flex max-w-xl items-center gap-2 border border-[#B2AC88] bg-white px-3 py-2 text-xs text-[#4B6E48]" role="status"><TemporaryChatIcon /><span>این چت ذخیره نمی‌شود و با بستن یا ترک صفحه از بین می‌رود.</span></div> : null}
        {messages.length === 0 ? <div className="mx-auto max-w-lg pt-20 text-center text-[#898989]"><div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center border border-[#B2AC88] bg-[#F2F0EF]">{ephemeral ? <TemporaryChatIcon className="h-9 w-9 text-[#4B6E48]" /> : <ChatIcon active className="h-9 w-9" />}</div><h1 className="mb-3 text-xl font-bold text-[#4B6E48]">{ephemeral ? "چت موقت" : "دستیار تماس‌ها"}</h1><p>درباره تماس‌ها، متن مکالمات، تحلیل‌ها و عملکرد اپراتورها سؤال کنید.</p></div> : null}
        {messages.map((message) => {
          const user = message.role === "user";
          const charts = (message.tool_runs || []).flatMap((run) => run.charts || []);
          return <ConversationBubble key={message.id} side={user ? "user" : "assistant"} wide={Boolean(message.sources?.length || charts.length)}>
              {!user ? <ToolTimeline runs={message.tool_runs || []} active={message.status === "running"} /> : null}
              {message.status === "running" && !message.content ? <TypingIndicator label={phases[message.id]} /> : <MarkdownMessage content={message.content} />}
              {!user ? <AssistantCharts charts={charts} /> : null}
              {message.sources?.length ? <CallSources sources={message.sources} expandedCallId={expandedCallId} onToggle={toggleCallSource} /> : null}
          </ConversationBubble>;
        })}
        <div ref={endRef} />
      </div>
      <form className="flex shrink-0 items-start gap-2 border-t border-[#B2AC88] bg-white p-3" onSubmit={submit}><div className="relative min-w-0 flex-1 bg-[#F2F0EF]"><textarea ref={inputRef} rows={1} className="input h-[4.25rem] min-h-[4.25rem] resize-none overflow-y-hidden border-0 bg-transparent pb-7 pt-3 text-slate-900 focus:!border-[#4B6E48]" value={text} onChange={(event) => { setText(event.target.value); requestAnimationFrame(resizeInput); }} onKeyDown={(event) => { if (event.ctrlKey && event.key === "Enter") { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="سؤال خود را بنویسید…" />{!text && <p className="pointer-events-none absolute inset-x-3 bottom-2 truncate text-[11px] text-[#898989]"><TypingPromptGuide /></p>}</div><button type="submit" className="inline-flex min-h-12 w-12 shrink-0 self-stretch items-center justify-center bg-[#4B6E48] text-[#F2F0EF] transition hover:bg-[#3F5D3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#4B6E48] disabled:cursor-not-allowed disabled:bg-[#898989] disabled:opacity-60" aria-label="ارسال پیام" title="ارسال پیام" disabled={sending || !text.trim()}><SendIcon /></button></form>
    </section>
    <ErrorBox message={error} />
    <ConfirmDialog
      open={Boolean(confirmation)}
      title={confirmation?.action === "delete" ? "حذف گفتگو" : "آرشیو گفتگو"}
      description={confirmation?.action === "delete" ? "آیا از حذف این گفتگو مطمئن هستید؟ این عملیات قابل بازگشت نیست." : "آیا از آرشیو کردن این گفتگو مطمئن هستید؟"}
      confirmLabel={confirmation?.action === "delete" ? "حذف" : "آرشیو"}
      destructive={confirmation?.action === "delete"}
      onCancel={() => setConfirmation(null)}
      onConfirm={() => void confirmConversationAction()}
    />
  </div>;
}
