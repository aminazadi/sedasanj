import { Fragment, useEffect, useState, type ReactNode } from "react";
import { request } from "../api";
import type { IconName } from "../components/SiteIcon";

export interface TitledText { title: string; text: string }
export interface AboutContent {
  hero_title: string; hero_text: string;
  story_title: string; story_paragraphs: string[];
  values_title: string; values: Array<TitledText & { icon: IconName | "" }>;
  outcome_title: string; outcome_text: string; outcome_button: string; outcome_link: string;
}
export interface ContactMethod { icon: "sales" | "mail" | "clock" | "phone" | "location" | "chat"; label: string; value: string; href: string }
export interface ContactContent {
  hero_title: string; hero_text: string;
  aside_title: string; methods: ContactMethod[]; form_title: string; form_message_placeholder: string;
  form_submit: string; form_success: string; }
export interface LegalContent { title: string; intro: string; updated_label: string; sections: Array<{ title: string; body: string }> }

export type SitePageState<T> = { status: "loading" } | { status: "error" } | { status: "ready"; content: T };

/** Loads a CMS-managed public page; `reload` retries after a failure. */
export function useSitePage<T>(slug: string): { state: SitePageState<T>; reload: () => void } {
  const [state, setState] = useState<SitePageState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    request<{ content: T }>(`/v1/site/pages/${slug}`)
      .then((page) => live && setState({ status: "ready", content: page.content }))
      .catch(() => live && setState({ status: "error" }));
    return () => { live = false; };
  }, [slug, attempt]);
  return { state, reload: () => setAttempt((value) => value + 1) };
}

/** Plain-text titles: a new line breaks the line and **text** is highlighted. */
export function RichTitle({ text }: { text: string }): ReactNode {
  return text.split("\n").map((line, index) => <Fragment key={index}>
    {index > 0 && <br />}
    {line.split(/\*\*(.+?)\*\*/g).map((part, at) => at % 2 ? <em key={at}>{part}</em> : part)}
  </Fragment>);
}

/** Paragraphs separated by blank lines; single newlines stay as line breaks. */
export function Paragraphs({ text }: { text: string }): ReactNode {
  return text.split(/\n\s*\n/).filter((block) => block.trim()).map((block, index) => <p key={index}>{block.split("\n").map((line, at) => <Fragment key={at}>{at > 0 && <br />}{line}</Fragment>)}</p>);
}
