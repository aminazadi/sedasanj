import type { MeetingActionItem, MeetingSegment, MeetingSpeaker, MeetingStatus } from "../types";

export type MeetingTab = "minutes" | "transcript" | "speakers";
export interface MeetingFilters { q: string; status: string; owner_id: string; from: string; to: string }
export interface SpeakerTurn {
  id: string;
  speaker_idx: number;
  label: string;
  side: "user" | "assistant";
  t_start_ms: number;
  t_end_ms: number;
  text: string;
}

export const MEETING_TABS: MeetingTab[];
export const MEETING_ACTIVE_STATUSES: MeetingStatus[];
export const MEETING_FAILED_STATUSES: MeetingStatus[];
export const MEETING_FILTER_KEYS: Array<keyof MeetingFilters>;
export const TURN_MERGE_GAP_MS: number;
export function isMeetingActive(status: string): boolean;
export function meetingFiltersFromSearch(search: URLSearchParams): MeetingFilters;
export function meetingPageFromSearch(search: URLSearchParams): number;
export function searchFromMeetingFilters(filters: Partial<MeetingFilters>, page?: number, pageSize?: string | number | null): URLSearchParams;
export function meetingTabFromSearch(search: URLSearchParams): MeetingTab;
export function speakerSide(speakerIdx: number): "user" | "assistant";
export function speakerColor(speakerIdx: number, palette: readonly string[]): string;
export function speakerLabel(speakerIdx: number, speakers: MeetingSpeaker[]): string;
export function buildSpeakerTurns(segments: MeetingSegment[], speakers?: MeetingSpeaker[], mergeGapMs?: number): SpeakerTurn[];
export function activeTurnId(turns: SpeakerTurn[], positionMs: number): string | null;
export function formatClock(ms: number): string;
export function meetingProgress(status: string, progressPct: number): number;
export function meetingTranscriptText(title: string, turns: SpeakerTurn[]): string;
export function meetingMinutesMarkdown(minutes: { summary: string; decisions: string[]; action_items: MeetingActionItem[] }): string;
export function meetingPipelineStatus(status: string, progressPct: number, inputKind?: string): string;
