import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { chart } from "@cbi/web-shared/theme";
import { useResource } from "@cbi/web-shared/lib/useResource";
import { fetchAuthorizedBlob, fmt, request } from "../api";
import { CAN_MANAGE_MEETINGS, isOrgAdmin, useAuth } from "../auth";
import AudioWaveformPlayer from "../components/AudioWaveformPlayer";
import ConfirmDialog from "../components/ConfirmDialog";
import ConversationBubble from "../components/ConversationBubble";
import DocumentActions from "../components/DocumentActions";
import FormDialog from "../components/FormDialog";
import MarkdownMessage from "../components/MarkdownMessage";
import MeetingStatusBadge from "../components/MeetingStatusBadge";
import OverflowMenu from "../components/OverflowMenu";
import ProcessingTimeline from "../components/ProcessingTimeline";
import { Empty, ErrorBox, Loading, ProcessingCard, type PipelineStep } from "../components/Widgets";
import {
  MEETING_FAILED_STATUSES,
  MEETING_TABS,
  activeTurnId,
  buildSpeakerTurns,
  formatClock,
  isMeetingActive,
  meetingMinutesMarkdown,
  meetingPipelineStatus,
  meetingProgress,
  meetingTabFromSearch,
  meetingTranscriptText,
  speakerColor,
} from "../lib/meetingsHelpers.mjs";
import type { MeetingTab } from "../lib/meetingsHelpers.mjs";
import type { MeetingDetail } from "../types";
import { downloadTextFile, safeDownloadName } from "../utils/download";

const POLL_INTERVAL_MS = 3000;

const TAB_LABELS: Record<MeetingTab, string> = {
  minutes: "صورت‌جلسه",
  transcript: "متن جلسه",
  speakers: "گوینده‌ها",
};

const MEETING_PIPELINE_STEPS: PipelineStep[] = [
  { label: "دریافت صدا", hint: "دریافت تکه‌های ضبط", statuses: ["receiving"] },
  { label: "تبدیل گفتار", hint: "پیاده‌سازی مکالمه", statuses: ["transcribing"] },
  { label: "تفکیک گوینده", hint: "تشخیص نوبت هر گوینده", statuses: ["diarizing"] },
  { label: "صورت‌جلسه", hint: "خلاصه، تصمیم‌ها و اقدام‌ها", statuses: ["minuting", "complete"] },
];

type SpeakerEdit = { speakerIdx: number; label: string };

export default function MeetingDetailPage() {
  const { meetingId } = useParams<{ meetingId: string }>();
  const navigate = useNavigate();
  const { session } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = meetingTabFromSearch(searchParams);
  const meeting = useResource<MeetingDetail>((signal) => request<MeetingDetail>(`/v1/meetings/${meetingId}`, { signal }), [meetingId]);
  const detail = meeting.data;

  const audioRef = useRef<HTMLAudioElement>(null);
  const pendingSeekMs = useRef<number | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioLoading, setAudioLoading] = useState(false);
  const [playbackMs, setPlaybackMs] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [speakerEdit, setSpeakerEdit] = useState<SpeakerEdit | null>(null);
  const [titleEdit, setTitleEdit] = useState<string | null>(null);

  const canManage = CAN_MANAGE_MEETINGS.includes(session?.role ?? "");
  const canDelete = isOrgAdmin(session?.role) || (detail !== undefined && detail.owner_id === session?.userId);
  const active = detail ? isMeetingActive(detail.status) : false;
  const failed = detail ? MEETING_FAILED_STATUSES.includes(detail.status) : false;
  const title = detail?.title || "جلسه بدون عنوان";

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => meeting.reload({ silent: true }), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [active, meeting.reload]);

  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl); }, [audioUrl]);

  // A click on a turn before the audio was loaded seeks as soon as the metadata is available.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audioUrl || !audio) return;
    const applyPending = () => {
      const target = pendingSeekMs.current;
      if (target === null) return;
      pendingSeekMs.current = null;
      audio.currentTime = target / 1000;
      void audio.play().catch(() => undefined);
    };
    if (audio.readyState >= 1) applyPending();
    audio.addEventListener("loadedmetadata", applyPending);
    return () => audio.removeEventListener("loadedmetadata", applyPending);
  }, [audioUrl]);

  const turns = useMemo(() => buildSpeakerTurns(detail?.segments ?? [], detail?.speakers ?? []), [detail?.segments, detail?.speakers]);
  const currentTurnId = audioUrl ? activeTurnId(turns, playbackMs) : null;
  const speakerStats = useMemo(() => {
    const stats = new Map<number, { turns: number; durationMs: number }>();
    for (const segment of detail?.segments ?? []) {
      const entry = stats.get(segment.speaker_idx) ?? { turns: 0, durationMs: 0 };
      entry.turns += 1;
      entry.durationMs += Math.max(0, segment.t_end_ms - segment.t_start_ms);
      stats.set(segment.speaker_idx, entry);
    }
    return stats;
  }, [detail?.segments]);
  const speakerRows = useMemo(() => {
    const known = new Map((detail?.speakers ?? []).map((speaker) => [speaker.speaker_idx, speaker]));
    for (const idx of speakerStats.keys()) if (!known.has(idx)) known.set(idx, { speaker_idx: idx, label: "", user_id: null });
    return [...known.values()].sort((a, b) => a.speaker_idx - b.speaker_idx);
  }, [detail?.speakers, speakerStats]);

  function selectTab(next: MeetingTab) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  const loadAudio = useCallback(async () => {
    if (audioUrl || audioLoading) return;
    setAudioLoading(true);
    setActionError(null);
    try {
      const blob = await fetchAuthorizedBlob(`/v1/meetings/${meetingId}/audio/content`);
      if (!blob || !blob.size) throw new Error("فایل صوتی این جلسه در دسترس نیست.");
      setAudioUrl(URL.createObjectURL(blob));
    } catch (err) {
      pendingSeekMs.current = null;
      setActionError((err as Error).message);
    } finally {
      setAudioLoading(false);
    }
  }, [audioLoading, audioUrl, meetingId]);

  function seekTo(ms: number) {
    const audio = audioRef.current;
    if (audioUrl && audio) {
      audio.currentTime = ms / 1000;
      void audio.play().catch(() => undefined);
      return;
    }
    pendingSeekMs.current = ms;
    void loadAudio();
  }

  async function runAction(path: string, method: "POST" | "PATCH", body: unknown, success: string) {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await request<unknown>(`/v1/meetings/${meetingId}${path}`, { method, body });
      setNotice(success);
      meeting.reload({ silent: true });
      return true;
    } catch (err) {
      setActionError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function deleteMeeting() {
    setBusy(true);
    setActionError(null);
    try {
      await request<void>(`/v1/meetings/${meetingId}`, { method: "DELETE" });
      navigate("/meetings", { replace: true });
    } catch (err) {
      setActionError((err as Error).message);
      setDeleteOpen(false);
      setBusy(false);
    }
  }

  async function saveSpeaker() {
    if (!detail || !speakerEdit) return;
    const label = speakerEdit.label.trim();
    if (!label) return;
    const speakers = speakerRows.map((speaker) => ({
      speaker_idx: speaker.speaker_idx,
      label: speaker.speaker_idx === speakerEdit.speakerIdx ? label : speaker.label,
      user_id: speaker.user_id,
    })).filter((speaker) => speaker.label);
    if (await runAction("", "PATCH", { speakers }, "نام گوینده ذخیره شد.")) setSpeakerEdit(null);
  }

  async function saveTitle() {
    const next = (titleEdit ?? "").trim();
    if (!next) return;
    if (await runAction("", "PATCH", { title: next }, "عنوان جلسه ذخیره شد.")) setTitleEdit(null);
  }

  function downloadTranscript() {
    if (!detail) return;
    downloadTextFile(`${safeDownloadName(title, "meeting")}-transcript.txt`, meetingTranscriptText(title, turns));
  }

  function downloadMinutes() {
    if (!detail?.minutes) return;
    downloadTextFile(`${safeDownloadName(title, "meeting")}-minutes.txt`, `${title}\n\n${meetingMinutesMarkdown(detail.minutes, title)}\n`);
  }

  if (!detail && !meeting.error) return <Loading />;
  if (!detail) {
    return (
      <div className="space-y-4">
        <ErrorBox message={meeting.error} />
        <Link className="btn-ghost inline-flex" to="/meetings">بازگشت به جلسات</Link>
      </div>
    );
  }

  const menuActions = [
    ...(canManage ? [{ label: "تغییر عنوان", onClick: () => setTitleEdit(detail.title ?? ""), disabled: busy }] : []),
    ...(canManage ? [{ label: "بازتحلیل صورت‌جلسه", onClick: () => void runAction("/reanalyze", "POST", undefined, "درخواست بازتحلیل ثبت شد."), disabled: busy || detail.status !== "complete" }] : []),
    ...(canManage ? [{ label: "تلاش مجدد پردازش", onClick: () => void runAction("/retry", "POST", undefined, "پردازش دوباره در صف قرار گرفت."), disabled: busy || !failed }] : []),
    { label: "دانلود متن جلسه", onClick: downloadTranscript, disabled: turns.length === 0 },
    { label: "دانلود صورت‌جلسه", onClick: downloadMinutes, disabled: !detail.minutes },
    ...(canDelete ? [{ label: "حذف جلسه", onClick: () => setDeleteOpen(true), disabled: busy }] : []),
  ];
  const minutesMarkdown = detail.minutes ? meetingMinutesMarkdown(detail.minutes, title) : "";
  const minutesMetadata: Array<[string, string]> = [["زمان جلسه", fmt.dateTime(detail.started_at)]];
  if (detail.owner_name) minutesMetadata.push(["برگزارکننده", detail.owner_name]);
  if (detail.duration_ms !== null) minutesMetadata.push(["مدت", fmt.duration(detail.duration_ms)]);
  if (detail.minutes) minutesMetadata.push(["نسخه صورت‌جلسه", fmt.int(detail.minutes.version)]);

  return (
    <div className="space-y-4">
      <section className="card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <Link className="text-xs text-[#4B6E48] hover:underline" to="/meetings">‹ بازگشت به جلسات</Link>
            <h1 className="mt-1 break-words text-xl font-black">{title}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-500">
              <MeetingStatusBadge status={detail.status} />
              <span>{fmt.dateTime(detail.started_at)}</span>
              {detail.duration_ms !== null ? <span>مدت {fmt.duration(detail.duration_ms)}</span> : null}
              {detail.owner_name ? <span>برگزارکننده: {detail.owner_name}</span> : null}
              {detail.speaker_count > 0 ? <span>{fmt.int(detail.speaker_count)} گوینده</span> : null}
            </p>
          </div>
          <div className="flex flex-wrap items-start gap-2">
            {minutesMarkdown ? (
              <DocumentActions key={detail.id} path={`/v1/meetings/${detail.id}/minutes/pdf`} title={title} kind="صورت‌جلسه" metadata={minutesMetadata}>
                <MarkdownMessage content={minutesMarkdown} print />
              </DocumentActions>
            ) : null}
            <OverflowMenu label="عملیات بیشتر جلسه" actions={menuActions} />
          </div>
        </div>
        {detail.audio_available ? (
          <div className="mt-5 border-t border-[color:var(--line)] pt-4">
            {audioUrl ? (
              <AudioWaveformPlayer
                audioRef={audioRef}
                downloadName={safeDownloadName(title, "meeting")}
                src={audioUrl}
                title="فایل صوتی جلسه"
                onTimeChange={(seconds) => setPlaybackMs(seconds * 1000)}
                onError={() => setActionError("مرورگر قادر به پخش این فایل صوتی نیست.")}
              />
            ) : (
              <button type="button" className="btn inline-flex items-center gap-2" onClick={() => void loadAudio()} disabled={audioLoading} aria-busy={audioLoading}>
                {audioLoading ? "در حال دریافت صدا…" : "پخش فایل صوتی جلسه"}
              </button>
            )}
          </div>
        ) : null}
      </section>

      {notice ? <div className="border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700" role="status">{notice}</div> : null}
      <ErrorBox message={actionError ?? meeting.error} />

      {detail.status !== "complete" && detail.status !== "canceled" ? (
        <ProcessingCard
          title="مسیر پردازش جلسه"
          steps={MEETING_PIPELINE_STEPS}
          status={meetingPipelineStatus(detail.status, detail.progress_pct, detail.input_kind)}
          progressPct={meetingProgress(detail.status, detail.progress_pct)}
          detail={detail.progress_detail}
        />
      ) : null}
      <ProcessingTimeline events={detail.processing_events ?? []} />

      <section className="card">
        <div className="mb-5 flex border border-[#B2AC88] bg-white p-1 sm:w-fit" role="tablist" aria-label="بخش‌های جلسه">
          {MEETING_TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              className={`min-h-9 flex-1 px-4 text-sm font-bold transition ${tab === name ? "bg-[#4B6E48] text-[#F2F0EF]" : "text-[#4B6E48] hover:bg-[#F2F0EF]"}`}
              onClick={() => selectTab(name)}
            >
              {TAB_LABELS[name]}
            </button>
          ))}
        </div>

        {tab === "minutes" ? (
          detail.minutes ? (
            <div className="space-y-6" role="tabpanel">
              {detail.minutes.content_md?.trim() ? <MarkdownMessage content={detail.minutes.content_md} /> : <MarkdownMessage content={detail.minutes.summary} />}
              {detail.minutes.content_md?.trim() ? null : detail.minutes.decisions.length ? (
                <div>
                  <h2 className="mb-2 font-bold">تصمیم‌ها</h2>
                  <ul className="list-disc space-y-1 pr-5 text-sm leading-7">
                    {detail.minutes.decisions.map((decision, index) => <li key={index}>{decision}</li>)}
                  </ul>
                </div>
              ) : null}
              {detail.minutes.content_md?.trim() ? null : detail.minutes.action_items.length ? (
                <div>
                  <h2 className="mb-2 font-bold">اقدام‌ها</h2>
                  <ul className="divide-y divide-slate-100 border border-[color:var(--line)]">
                    {detail.minutes.action_items.map((item, index) => (
                      <li key={index} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-3 text-sm">
                        <span className="min-w-0 flex-1 leading-7">{item.text}</span>
                        <span className="text-xs text-slate-500">
                          {item.assignee ? `مسئول: ${item.assignee}` : "بدون مسئول"}
                          {item.due ? ` · مهلت: ${item.due}` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : (
            <Empty>{active ? "صورت‌جلسه پس از پایان پردازش اینجا نمایش داده می‌شود." : failed ? "ساخت صورت‌جلسه ناموفق بود؛ «بازتحلیل صورت‌جلسه» یا «تلاش مجدد پردازش» را از منوی بالا بزنید." : "برای این جلسه صورت‌جلسه‌ای ثبت نشده است."}</Empty>
          )
        ) : null}

        {tab === "transcript" ? (
          turns.length === 0 ? (
            <Empty>{active ? "متن جلسه پس از پیاده‌سازی صدا اینجا نمایش داده می‌شود." : "برای این جلسه متنی ثبت نشده است."}</Empty>
          ) : (
            <div className="max-h-[680px] space-y-5 overflow-y-auto border border-slate-100 bg-slate-50/70 p-3 sm:p-4" role="tabpanel">
              {turns.map((turn) => (
                <ConversationBubble
                  key={turn.id}
                  side={turn.side}
                  ariaLabel={turn.label}
                  accentColor={speakerColor(turn.speaker_idx, chart.categorical)}
                  header={
                    <div className={`mb-1.5 flex items-center justify-between gap-6 text-[11px] ${turn.side === "user" ? "text-[#F2F0EF]/75" : "text-[#898989]"}`}>
                      <span className={`font-bold ${turn.side === "user" ? "text-[#F2F0EF]" : "text-[#4B6E48]"}`}>{turn.label}</span>
                      <span className="tabular-nums" dir="ltr">{formatClock(turn.t_start_ms)} — {formatClock(turn.t_end_ms)}</span>
                    </div>
                  }
                >
                  <button
                    type="button"
                    className={`block w-full whitespace-pre-wrap text-start text-sm leading-7 ${currentTurnId === turn.id ? "underline decoration-2 underline-offset-4" : ""}`}
                    dir="auto"
                    disabled={!detail.audio_available}
                    title={detail.audio_available ? "پخش از این لحظه" : undefined}
                    aria-label={detail.audio_available ? `پخش از ${formatClock(turn.t_start_ms)}: ${turn.text}` : undefined}
                    onClick={() => seekTo(turn.t_start_ms)}
                  >
                    {turn.text}
                  </button>
                </ConversationBubble>
              ))}
            </div>
          )
        ) : null}

        {tab === "speakers" ? (
          speakerRows.length === 0 ? (
            <Empty>{active ? "گوینده‌ها پس از تفکیک صدا اینجا نمایش داده می‌شوند." : "گوینده‌ای شناسایی نشده است."}</Empty>
          ) : (
            <ul className="divide-y divide-slate-100 border border-[color:var(--line)]" role="tabpanel">
              {speakerRows.map((speaker) => {
                const stats = speakerStats.get(speaker.speaker_idx);
                const label = speaker.label || `گوینده ${speaker.speaker_idx + 1}`;
                return (
                  <li key={speaker.speaker_idx} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className="h-3 w-3 shrink-0" style={{ backgroundColor: speakerColor(speaker.speaker_idx, chart.categorical) }} aria-hidden="true" />
                      <div className="min-w-0">
                        <p className="truncate font-bold">{label}</p>
                        <p className="text-xs text-slate-500">
                          {stats ? `${fmt.int(stats.turns)} بخش گفتار · ${fmt.duration(stats.durationMs)}` : "بدون گفتار"}
                        </p>
                      </div>
                    </div>
                    {canManage ? <button type="button" className="btn-ghost text-sm" onClick={() => setSpeakerEdit({ speakerIdx: speaker.speaker_idx, label: speaker.label })}>تغییر نام</button> : null}
                  </li>
                );
              })}
            </ul>
          )
        ) : null}
      </section>

      <ConfirmDialog
        open={deleteOpen}
        title="حذف جلسه"
        description="این جلسه، فایل صوتی، متن، گوینده‌ها و صورت‌جلسه برای همیشه حذف می‌شوند. این عملیات قابل بازگشت نیست."
        confirmLabel="حذف جلسه"
        destructive
        busy={busy}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={() => void deleteMeeting()}
      />
      <FormDialog
        open={speakerEdit !== null}
        title="تغییر نام گوینده"
        description="نام جدید در متن جلسه و صورت‌جلسه نمایش داده می‌شود."
        submitLabel="ذخیره نام"
        busy={busy}
        submitDisabled={!speakerEdit?.label.trim()}
        error={speakerEdit ? actionError : null}
        onSubmit={() => void saveSpeaker()}
        onClose={() => setSpeakerEdit(null)}
      >
        <label>
          <span>نام گوینده</span>
          <input value={speakerEdit?.label ?? ""} maxLength={80} autoFocus onChange={(event) => setSpeakerEdit((current) => current ? { ...current, label: event.target.value } : current)} />
        </label>
      </FormDialog>
      <FormDialog
        open={titleEdit !== null}
        title="تغییر عنوان جلسه"
        submitLabel="ذخیره عنوان"
        busy={busy}
        submitDisabled={!(titleEdit ?? "").trim()}
        error={titleEdit !== null ? actionError : null}
        onSubmit={() => void saveTitle()}
        onClose={() => setTitleEdit(null)}
      >
        <label>
          <span>عنوان</span>
          <input value={titleEdit ?? ""} maxLength={200} autoFocus onChange={(event) => setTitleEdit(event.target.value)} />
        </label>
      </FormDialog>
    </div>
  );
}
