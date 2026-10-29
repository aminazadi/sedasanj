---
name: sedasanj-changelog-commits
description: Format CHANGELOG entries and commit messages for this repository. Use at the end of every behavioural change.
---

# Changelog and commits

## Format (verified from `CHANGELOG.md` and `sedasanj/CHANGELOG.md`)

```
## YYYY-MM-DD — AMINAZADI

- Fixed <what> ...
- Added <what> ...
```

English only, one bullet per user-visible change, past-tense verb first (Fixed / Added / Changed / Replaced), newest date on top; reuse the existing date heading if today's is already there. Mention module versions when released ("module 1.3.7").

## Open decision

Two changelogs exist: the repo root `CHANGELOG.md` and `sedasanj/CHANGELOG.md`, with overlapping but different entries. The plan asks the maintainer to choose a single one. Until they do, update the root `CHANGELOG.md` and do not duplicate entries; if unsure, ask.

The FreePBX module also has its own `freepbx-module/changelog.md` (shown in Module Admin); module behaviour changes need an entry there too.

## Commits

- Short imperative English subject, e.g. "Fix missed-call idempotency conflict target" (matches `git log`).
- Do not commit `.DS_Store`, built zips (`asterisk-module-*.zip`), model downloads or secrets.
- Include the attribution line the environment requires.
