## 2026-11-05 — AMINAZADI

- Added staged rollout (`rollout_percent`), a forced minimum build (`min_supported_version_code`) and a stable/beta channel to Jalase-Negar releases, with a deterministic bucket from the app's anonymous install id and the matching admin fields.
- Added an anonymous, rate-limited install-result report endpoint, the `cbi_jalase_negar_update_install_total` counter, the `update_checksum_mismatch`, `update_downgrade_rejected` and `update_install_blocked` codes and their Persian help articles; migration 0104 also merges the two 0103 heads.
- Added server-side speaker profiles for Jalase-Negar: people and encrypted voiceprints with owner/organisation visibility, consent records, optimistic versions, tombstones and a commit-ordered change feed for cross-device sync.
- Added overlap and speaker-confidence fields to meeting segments and speaker-to-profile links on meeting speakers, keeping existing transcript hashes unchanged.
- Added the speaker error codes and Persian help articles, and the `VOICEPRINT_ENCRYPTION_KEY` setting.
