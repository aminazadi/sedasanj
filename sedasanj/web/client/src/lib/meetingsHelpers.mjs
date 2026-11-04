// Pure helpers for the meetings pages: URL state, speaker turns and exports. No browser APIs, so they run under node:test.

export const MEETING_TABS = ["minutes", "transcript", "speakers"];
export const MEETING_ACTIVE_STATUSES = ["receiving", "processing"];
export const MEETING_FAILED_STATUSES = ["failed_retryable", "failed_terminal"];
export const MEETING_FILTER_KEYS = ["q", "status", "owner_id", "from", "to"];
// Consecutive segments of one speaker closer than this are shown as a single turn.
export const TURN_MERGE_GAP_MS = 4000;

export function isMeetingActive(status) {
  return MEETING_ACTIVE_STATUSES.includes(status);
}

export function meetingFiltersFromSearch(search) {
  const filters = {};
  for (const key of MEETING_FILTER_KEYS) filters[key] = search.get(key) ?? "";
  return filters;
}

export function meetingPageFromSearch(search) {
  const page = Number(search.get("page") ?? "1");
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

export function searchFromMeetingFilters(filters, page = 1, pageSize = null) {
  const params = new URLSearchParams();
  for (const key of MEETING_FILTER_KEYS) {
    const value = String(filters[key] ?? "").trim();
    if (value) params.set(key, value);
  }
  if (page > 1) params.set("page", String(page));
  if (pageSize) params.set("page_size", String(pageSize));
  return params;
}

export function meetingTabFromSearch(search) {
  const tab = search.get("tab");
  return MEETING_TABS.includes(tab) ? tab : "minutes";
}

// Even speaker indexes sit on one side of the conversation and odd ones on the other.
export function speakerSide(speakerIdx) {
  return speakerIdx % 2 === 0 ? "user" : "assistant";
}

export function speakerColor(speakerIdx, palette) {
  if (!palette.length) return "";
  return palette[((speakerIdx % palette.length) + palette.length) % palette.length];
}

export function speakerLabel(speakerIdx, speakers) {
  const named = speakers.find((speaker) => speaker.speaker_idx === speakerIdx)?.label?.trim();
  return named || `گوینده ${speakerIdx + 1}`;
}

// Orders segments by time and merges neighbours of the same speaker into turns.
export function buildSpeakerTurns(segments, speakers = [], mergeGapMs = TURN_MERGE_GAP_MS) {
  const ordered = [...segments]
    .filter((segment) => segment.text && segment.text.trim())
    .sort((a, b) => a.t_start_ms - b.t_start_ms);
  const turns = [];
  for (const segment of ordered) {
    const last = turns[turns.length - 1];
    const text = segment.text.trim();
    if (last && last.speaker_idx === segment.speaker_idx && segment.t_start_ms - last.t_end_ms <= mergeGapMs) {
      last.text = `${last.text} ${text}`;
      last.t_end_ms = Math.max(last.t_end_ms, segment.t_end_ms);
      continue;
    }
    turns.push({
      id: `${segment.speaker_idx}-${segment.t_start_ms}`,
      speaker_idx: segment.speaker_idx,
      label: speakerLabel(segment.speaker_idx, speakers),
      side: speakerSide(segment.speaker_idx),
      t_start_ms: segment.t_start_ms,
      t_end_ms: segment.t_end_ms,
      text,
    });
  }
  return turns;
}

// The turn being played at `positionMs`: the last turn that started at or before it.
export function activeTurnId(turns, positionMs) {
  let active = null;
  for (const turn of turns) {
    if (turn.t_start_ms <= positionMs) active = turn.id;
    else break;
  }
  return active;
}

export function formatClock(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  const two = (value) => String(value).padStart(2, "0");
  return hours > 0 ? `${hours}:${two(minutes)}:${two(seconds)}` : `${two(minutes)}:${two(seconds)}`;
}

export function meetingProgress(status, progressPct) {
  if (status === "complete") return 100;
  const value = Number.isFinite(progressPct) ? progressPct : 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function meetingTranscriptText(title, turns) {
  const lines = turns.map((turn) => `[${formatClock(turn.t_start_ms)}] ${turn.label}: ${turn.text}`);
  return `${title}\n\n${lines.join("\n\n")}\n`;
}

export function meetingMinutesMarkdown(minutes, title) {
  if (typeof minutes.content_md === "string" && minutes.content_md.trim()) {
    const content = minutes.content_md.trim();
    const heading = /^#[ \t]+(.+?)[ \t]*#*(?:\r?\n|$)/.exec(content);
    return title && heading?.[1].trim() === title.trim() ? content.slice(heading[0].length).trim() : content;
  }
  const parts = [minutes.summary.trim()];
  if (minutes.decisions.length) parts.push(`## تصمیم‌ها\n\n${minutes.decisions.map((item) => `- ${item}`).join("\n")}`);
  if (minutes.action_items.length) {
    const rows = minutes.action_items.map((item) => `- ${item.text}${item.assignee ? ` (مسئول: ${item.assignee})` : ""}${item.due ? ` — مهلت: ${item.due}` : ""}`);
    parts.push(`## اقدام‌ها\n\n${rows.join("\n")}`);
  }
  return parts.filter(Boolean).join("\n\n");
}

// Maps a meeting to the pseudo-status the pipeline card understands. The progress bands are a
// presentation assumption (transcription first, then speakers, then minutes) until the API reports the stage.
export function meetingPipelineStatus(status, progressPct, inputKind = "audio") {
  if (status === "receiving") return "receiving";
  if (status !== "processing") return status;
  // Text meetings arrive already transcribed: the only server stage is the minutes.
  if (inputKind === "text") return "minuting";
  const progress = meetingProgress(status, progressPct);
  if (progress < 50) return "transcribing";
  if (progress < 75) return "diarizing";
  return "minuting";
}
