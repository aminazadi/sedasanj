import { useEffect, useMemo, useState } from "react";
import { Icon } from "./SiteIcon";
import { SafeLink } from "./SitePageParts";
import { useSitePage } from "../lib/sitePages";

export interface AuthAsideMessage { text: string; cta_text: string; cta_link: string }
export interface AuthAsideContent { messages: AuthAsideMessage[]; type_speed_ms: number; hold_seconds: number }

/** Shown until the admin-managed content loads, and when it cannot be loaded. */
const FALLBACK: AuthAsideContent = { messages: [{ text: "هر تماس، یک فرصت برای شنیده‌شدن", cta_text: "", cta_link: "" }], type_speed_ms: 55, hold_seconds: 4 };
const ERASE_MS = 14;
const GAP_MS = 350;

type Phase = "typing" | "holding" | "erasing";

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Types each message, holds it, erases it and moves on to the next one. */
function useTypedMessages({ messages, type_speed_ms, hold_seconds }: AuthAsideContent, paused: boolean) {
  const [index, setIndex] = useState(0);
  const [length, setLength] = useState(0);
  const [phase, setPhase] = useState<Phase>("typing");
  const reduced = useMemo(prefersReducedMotion, []);
  const count = messages.length;
  const current = Math.min(index, count - 1);
  const chars = useMemo(() => Array.from(messages[current].text), [messages, current]);

  useEffect(() => { setIndex(0); setLength(0); setPhase("typing"); }, [messages]);

  useEffect(() => {
    if (paused) return;
    const advance = () => { setIndex((value) => (value + 1) % count); setLength(0); setPhase("typing"); };
    let timer: number | undefined;
    if (reduced) {
      setLength(chars.length);
      if (count > 1) timer = window.setTimeout(advance, hold_seconds * 1000);
    } else if (phase === "typing") {
      if (length < chars.length) timer = window.setTimeout(() => setLength(length + 1), type_speed_ms);
      else if (count > 1) timer = window.setTimeout(() => setPhase("erasing"), hold_seconds * 1000);
    } else if (phase === "erasing") {
      if (length > 0) timer = window.setTimeout(() => setLength(length - 1), ERASE_MS);
      else timer = window.setTimeout(advance, GAP_MS);
    }
    return () => window.clearTimeout(timer);
  }, [paused, reduced, phase, length, chars, count, type_speed_ms, hold_seconds]);

  const typed = reduced ? messages[current].text : chars.slice(0, length).join("");
  const finished = reduced || (phase === "typing" && length >= chars.length);
  return { current, typed, finished, typing: !reduced && phase !== "holding" && !finished };
}

/** Decorative green panel (same palette as the panel sidebars) with admin-managed typed messages. */
export default function AuthAside() {
  const { state } = useSitePage<AuthAsideContent>("auth_aside");
  const content = state.status === "ready" && state.content.messages.length ? state.content : FALLBACK;
  const [paused, setPaused] = useState(false);
  const { current, typed, finished, typing } = useTypedMessages(content, paused);
  const message = content.messages[current];
  const showCta = finished && !!message.cta_text && !!message.cta_link;

  return <aside className="auth-aside" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
    <div className="auth-aside-art" aria-hidden="true"><i/><i/><i/><i/></div>
    <div className="auth-aside-body">
      <h2 className="auth-aside-text"><span className="sr-only">{message.text}</span><span aria-hidden="true">{typed}</span><span className={`auth-aside-caret${typing ? " is-typing" : ""}`} aria-hidden="true"/></h2>
      <div className={`auth-aside-cta${showCta ? " is-visible" : ""}`}>
        {message.cta_text && message.cta_link && <SafeLink className="auth-aside-button" href={message.cta_link}>{message.cta_text}<Icon name="arrow" size={18}/></SafeLink>}
      </div>
      {content.messages.length > 1 && <ol className="auth-aside-steps" aria-hidden="true">{content.messages.map((_, at) => <li key={at} className={at === current ? "is-active" : ""}/>)}</ol>}
    </div>
  </aside>;
}
