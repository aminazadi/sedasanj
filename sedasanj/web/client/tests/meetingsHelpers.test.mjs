import assert from "node:assert/strict";
import test from "node:test";
import {
  activeTurnId,
  buildSpeakerTurns,
  formatClock,
  isMeetingActive,
  meetingFiltersFromSearch,
  meetingMinutesMarkdown,
  meetingPageFromSearch,
  meetingProgress,
  meetingTabFromSearch,
  meetingTranscriptText,
  searchFromMeetingFilters,
  speakerColor,
  speakerLabel,
  speakerSide,
} from "../src/lib/meetingsHelpers.mjs";

test("filters round-trip through the URL and drop empty values", () => {
  const params = searchFromMeetingFilters({ q: " بودجه ", status: "complete", owner_id: "", from: "2026-01-01", to: "" }, 3, "25");
  assert.equal(params.toString(), new URLSearchParams({ q: "بودجه", status: "complete", from: "2026-01-01", page: "3", page_size: "25" }).toString());
  assert.deepEqual(meetingFiltersFromSearch(params), { q: "بودجه", status: "complete", owner_id: "", from: "2026-01-01", to: "" });
  assert.equal(meetingPageFromSearch(params), 3);
  assert.equal(searchFromMeetingFilters({}, 1).toString(), "");
});

test("invalid page and tab values fall back to defaults", () => {
  assert.equal(meetingPageFromSearch(new URLSearchParams("page=-2")), 1);
  assert.equal(meetingPageFromSearch(new URLSearchParams("page=abc")), 1);
  assert.equal(meetingTabFromSearch(new URLSearchParams("tab=speakers")), "speakers");
  assert.equal(meetingTabFromSearch(new URLSearchParams("tab=bogus")), "minutes");
  assert.equal(meetingTabFromSearch(new URLSearchParams()), "minutes");
});

test("only receiving and processing meetings are polled", () => {
  assert.equal(isMeetingActive("receiving"), true);
  assert.equal(isMeetingActive("processing"), true);
  for (const status of ["complete", "failed_retryable", "failed_terminal", "canceled"]) assert.equal(isMeetingActive(status), false);
});

test("speakers alternate sides by index parity and cycle palette colours", () => {
  assert.deepEqual([0, 1, 2, 3].map(speakerSide), ["user", "assistant", "user", "assistant"]);
  assert.equal(speakerColor(0, ["a", "b"]), "a");
  assert.equal(speakerColor(3, ["a", "b"]), "b");
  assert.equal(speakerColor(1, []), "");
});

test("speaker labels use the renamed speaker or a numbered default", () => {
  const speakers = [{ speaker_idx: 1, label: " علی ", user_id: null }];
  assert.equal(speakerLabel(1, speakers), "علی");
  assert.equal(speakerLabel(2, speakers), "گوینده 3");
});

test("turns are time ordered and merge close segments of the same speaker only", () => {
  const segments = [
    { speaker_idx: 1, t_start_ms: 9000, t_end_ms: 12000, text: "سوم" },
    { speaker_idx: 0, t_start_ms: 0, t_end_ms: 2000, text: "اول" },
    { speaker_idx: 0, t_start_ms: 3000, t_end_ms: 5000, text: "ادامه" },
    { speaker_idx: 0, t_start_ms: 20000, t_end_ms: 21000, text: "دیرتر" },
    { speaker_idx: 2, t_start_ms: 30000, t_end_ms: 31000, text: "  " },
  ];
  const turns = buildSpeakerTurns(segments, [{ speaker_idx: 1, label: "رضا", user_id: null }]);
  assert.deepEqual(turns.map((turn) => [turn.label, turn.text, turn.t_start_ms, turn.t_end_ms]), [
    ["گوینده 1", "اول ادامه", 0, 5000],
    ["رضا", "سوم", 9000, 12000],
    ["گوینده 1", "دیرتر", 20000, 21000],
  ]);
  assert.deepEqual(turns.map((turn) => turn.side), ["user", "assistant", "user"]);
});

test("active turn follows the playback position", () => {
  const turns = buildSpeakerTurns([
    { speaker_idx: 0, t_start_ms: 0, t_end_ms: 1000, text: "a" },
    { speaker_idx: 1, t_start_ms: 5000, t_end_ms: 6000, text: "b" },
  ]);
  assert.equal(activeTurnId(turns, -1), null);
  assert.equal(activeTurnId(turns, 4999), "0-0");
  assert.equal(activeTurnId(turns, 5000), "1-5000");
});

test("clock and progress helpers clamp their input", () => {
  assert.equal(formatClock(65000), "01:05");
  assert.equal(formatClock(3725000), "1:02:05");
  assert.equal(formatClock(-5), "00:00");
  assert.equal(meetingProgress("complete", 10), 100);
  assert.equal(meetingProgress("processing", 140), 100);
  assert.equal(meetingProgress("processing", Number.NaN), 0);
});

test("exports carry the title, timestamps and speaker names", () => {
  const turns = buildSpeakerTurns([{ speaker_idx: 0, t_start_ms: 61000, t_end_ms: 62000, text: "سلام" }]);
  assert.equal(meetingTranscriptText("جلسه", turns), "جلسه\n\n[01:01] گوینده 1: سلام\n");
  const markdown = meetingMinutesMarkdown({
    summary: "خلاصه",
    decisions: ["تصمیم یک"],
    action_items: [{ text: "ارسال گزارش", assignee: "سارا", due: null }],
  });
  assert.match(markdown, /## تصمیم‌ها\n\n- تصمیم یک/);
  assert.match(markdown, /- ارسال گزارش \(مسئول: سارا\)/);
});

test("rendered minutes win over the flat fields, and text meetings go straight to the minutes stage", async () => {
  const { meetingPipelineStatus } = await import("../src/lib/meetingsHelpers.mjs");
  assert.equal(meetingMinutesMarkdown({ content_md: "  # صورت‌جلسه\n- الف  ", summary: "x", decisions: [], action_items: [] }), "# صورت‌جلسه\n- الف");
  assert.equal(meetingPipelineStatus("processing", 5, "text"), "minuting");
  assert.equal(meetingPipelineStatus("processing", 5), "transcribing");
  assert.equal(meetingPipelineStatus("complete", 100, "text"), "complete");
});

test("processing meetings map to a pipeline stage by progress band", async () => {
  const { meetingPipelineStatus } = await import("../src/lib/meetingsHelpers.mjs");
  assert.equal(meetingPipelineStatus("receiving", 0), "receiving");
  assert.equal(meetingPipelineStatus("processing", 10), "transcribing");
  assert.equal(meetingPipelineStatus("processing", 60), "diarizing");
  assert.equal(meetingPipelineStatus("processing", 90), "minuting");
  assert.equal(meetingPipelineStatus("complete", 0), "complete");
  assert.equal(meetingPipelineStatus("failed_retryable", 40), "failed_retryable");
});
