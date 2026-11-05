# Changelog — Jalase Negar

## 2026-11-05 — AMINAZADI

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
