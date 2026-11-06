# Changelog — Jalase Negar

## 2026-11-06 — AMINAZADI

- Fixed live transcription discarding speech when the phone fell behind: skipped and shed spans (up to 10 minutes of audio) are now kept and decoded later when the engine is idle, or for up to 30 seconds after stopping, and `JN-ASR-0001` is cleared once they are recovered. The stop timeout of the live engine is now 45 seconds.
- Fixed the live duplicate filter dropping the same short word (for example "بله") said by two different speakers within 1.2 seconds; it now compares only lines of the same or an unknown speaker.
- Added Android store flavors `direct`, `bazaar` and `myket` (same application ID and signing certificate). The Bazaar and Myket builds drop the self-updater: `REQUEST_INSTALL_PACKAGES`, `UPDATE_PACKAGES_WITHOUT_USER_ACTION` and the install receiver are removed, and the Settings update card is hidden (`--dart-define=STORE=<channel>`).
- Added macOS and Windows projects: macOS sandbox entitlements for microphone, camera, network and file picking; Windows uses `sqflite_common_ffi` and `just_audio_windows`; the foreground service is skipped on desktop and the QR scanner is hidden on Windows.
- Added `scripts/build-jalase-negar-release.sh` (APKs, unsigned iOS archive/IPA for SibApp and Anardooni, macOS zip), a GitHub Actions workflow for the Windows build and `docs/release-builds.md`. Windows and signed iOS builds are not verified yet.

## 2026-11-05 — AMINAZADI

- Changed the models screen to a single "download, install and activate" action with overall progress; model names and sizes are no longer shown. Only the recommended Shenava Koochik 1.5 RNNT speech model is offered: the other speech models were removed from the catalog and their files are deleted from the phone on the next models load (a retired selection is replaced by the remaining model). The intro and tour texts were updated to match.

- Added an intro slide (animated meeting-room illustration) recommending high-quality clip-on (lavalier) microphones such as RØDE, BOYA and Holyland, with a drawn lavalier-on-collar illustration for the best meeting output, a tour step that highlights the microphone-selection button on the recording screen, and turned the "connect to SedaSanj" tour step into a numbered connection guide.

- Replaced the recording attendee section with an outlined button below the timer instructions and removable selected-person chips alongside it in a horizontally scrollable row.

- Fixed main-tab headers with consistent 16-pixel horizontal spacing and unified the add-person and model-download actions using the same square bordered button.

- Added choosing the people present before recording: an optional attendees card on the ready-to-record screen with a multi-select sheet and "add new person" (full consent and voice sample, then back to the sheet with the person selected). Attendees are stored with the meeting (database v11 `meeting_attendees`), sent to SedaSanj with the session, given a small head start in speaker matching (live and precise pass), listed first in the speaker picker and shown on the meeting detail. A failed save only logs `JN-REC-0005`; recording continues.
- Changed auto-send: a new recording is first analysed for its speakers (database v10 `speakers_state`), and only then sent to SedaSanj. The analysis resumes after an app restart and releases the meeting even when models are missing or it fails, so nothing is held back for good.
- Showed the app's loading mark with one line of text in the list and the detail screen while speakers are extracted, and hid the send icon meanwhile.
- Added an empty state (image, text and "extract speakers" button) to the speakers tab when none were extracted.
- Reworked the meeting detail screen into tabs (transcript editor first, speakers second) and added a "send to SedaSanj" icon to the detail header and list tiles for meetings that were not sent or failed.
- Simplified the list loading state while sending to the app's processing mark and one line of text, with no progress bar or tinted background.
- Fixed auto-send marking a meeting failed when an earlier pass had already finished it on the server (`meeting_closed` on the transcript upload); it is now followed as processing.
- Integrated background updates with the released People and Guide features and kept debug installs separate with the `.dev` application ID suffix.
- Added automatic background updates: a WorkManager check about every 8 hours on an unmetered network, a resumable download with SHA-256, higher-versionCode and same-signing-certificate checks, and a PackageInstaller install (no confirmation on Android 12+ where the phone allows it) only at a calm moment: not recording, nothing left to upload or sync, app in the background, free space of at least twice the APK and 30% battery or charging.
- Added a one-time Persian explainer for the "install unknown apps" permission, a one-tap notification when Android still asks for confirmation, the existing browser download as the last fallback, and a quiet "updated" toast after an update.
- Fixed the app version sent when pairing, which was hard-coded to 2.0.0; it now comes from the installed package.
- Parsed `sha256`, `min_sdk` and `mandatory` from update offers and send an anonymous random install id for staged rollouts. OEM silent-install behaviour is not verified on real phones yet.

- Added "People and voice": a people list, consent screen, 5-prompt voice enrolment with quality gates (speech length, SNR, clipping), private/organisation sharing toggle, rename, sample delete and person delete.
- Added the speaker-embedding (CAM++) and pyannote segmentation models to the model catalog and the models screen.
- Added live speaker identification in the VAD engine: cosine matching against enrolled centroids, online "ناشناس N" clustering for unknown voices, and overlap layer A (two-speaker label and low confidence on overlapping speech, embeddings taken from non-overlap frames only).
- Added `نام: متن` lines in the live panel and a speaker card on the meeting detail screen with a per-line speaker picker, rename of all lines of an unknown speaker, split into two speakers, a low-confidence warning, an overlap badge and copy with speaker names.
- Added "precise processing" (overlap layer B): whole-file diarization mapped to enrolled people; lines edited by hand are never changed.
- Added sqflite schema v9 (`people`, `voiceprints`, `sync_outbox`, and speaker/overlap/confidence columns on `segments`) with a tested v8 to v9 migration.
- Added `SyncEngine` for speaker profiles (outbox push, then pull from a cursor, 409 rebase, tombstones) triggered by connectivity, app start, pairing, local change and a 15-minute timer; embeddings are encrypted at rest with AES-256-GCM and never logged.
- Added `speakers`, `overlap` and `speaker_confidence` to `PUT /transcript`.
- Fixed `text_sync_pending` never retrying: the upload queue now re-sends pending edited texts automatically with the same backoff as audio uploads.
- Known limits: matching thresholds (0.50 / margin 0.06 / unknown join 0.55) and enrolment quality limits are not tuned on real phones; Persian accuracy, battery and layer B memory use on devices, and iOS are not verified.
