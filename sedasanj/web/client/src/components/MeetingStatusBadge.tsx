import { MEETING_STATUS_LABELS } from "../api";

const TONES: Record<string, string> = {
  receiving: "info",
  processing: "info",
  complete: "success",
  failed_retryable: "orange",
  failed_terminal: "danger",
  canceled: "neutral",
};

export default function MeetingStatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${TONES[status] ?? "neutral"}`}><span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />{MEETING_STATUS_LABELS[status] ?? status}</span>;
}
