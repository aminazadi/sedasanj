---
name: asterisk-recording-pipeline
description: Reason about the Asterisk/FreePBX recording path (MixMonitor, CDR/CEL, stereo mixing, upload queue) used by the Seda Sanj module. Use when fixing lost, late, duplicate or malformed recordings and missed calls.
---

# Asterisk recording pipeline

## Flow in this repo

MixMonitor (configured via `freepbx-module/dialplan/globals-custom-mixmon.conf`) → post-record command `freepbx-module/engine/bin/mix-stereo.php` → staging (`engine/src/Staging.php`) → queue (`Queue.php`, `QueueWorker.php`, SQLite or JSON backend via `StateStore.php`) → `Uploader.php` → `POST` to the SedaSanj ingest API. `Sweeper.php` reconciles recordings the hook missed; `MissedCallPoller.php` and `CdrSource.php` read CDR for missed calls; voicemail goes through `VoicemailSweeper.php` and `Voicemail/`.

## Facts and rules

- MixMonitor options include `a b B c d D i m n p P r() t() s() v V W`; the command argument runs after recording ends and variables are expanded at MixMonitor start (Asterisk 22 docs).
- Missed-call detection depends on `cdr.conf` `unanswered=yes`; the module must report when it is off.
- CDR rows can be finalized after the recording file is closed. Never assume CDR is complete when the file appears; retry with a bounded delay.
- Stereo (channel-split) versus mono: merge failures in `mix-stereo.php` currently may never reach the log; every failure path must log a coded event.
- Idempotency: server ingest uses per-tenant unique IDs; client resends must carry the same `uniqueid`. Recent fix: missed-call conflict target uses the real unique columns (see `CHANGELOG.md` 2026-10-29).
- Race risks to check on any change: sweeper vs hook both enqueuing the same file; file still being written; clock skew between PBX and API; disk full during staging; SQLite corruption. Several of these have no code path today (⚠ planned in the error catalog).
- Destination labels in the dialplan can be non-numeric; upload code must tolerate them (commit 28e865d).

## How to verify

1. Stub-HTTP tests for upload statuses (401/402/404/413/415/422/429/5xx/timeout) as planned under `freepbx-module/tests/`.
2. Lab: place an answered call, an unanswered call and a voicemail on each FreePBX version; confirm exactly one server record per call.
3. ⚠ Any timing claim (CDR delay, sweeper interval) needs a lab measurement before it is documented.
