# Changelog

## 2026-10-28 — AMINAZADI

- Corrected module-release back-link arrow direction across the administration pages.
- Fixed FreePBX module uploads by provisioning and backing up a persistent release-signing key and embedding its public key into every published module archive.
- Added recoverable Redis startup repair for corrupted AOF persistence and documented the required host memory-overcommit configuration.
- Fixed API and worker image builds by retrying Python package mirrors independently when an index returns a truncated or malformed response.
- Persisted Sedasanj and AISERVICE model downloads in Git-ignored, build-excluded project-root directories and reused them across deployments.
- Added automatic one-time migration from the previous Docker model volumes.

## 2026-10-28 — AMINAZADI

- Configured the official PyPI index as an additional package source during API and worker image builds.
- Replaced the official PyPI extra index with Aliyun and Tsinghua mirrors for API and worker image builds.
- Added a PyPI fallback when the configured package mirror fails during API image dependency installation.

## 2026-10-28 — AMINAZADI

- Fixed FreePBX configuration imports by supporting the optional missed_calls section and reporting precise section validation errors.
- Completed the FreePBX missed-call upload path with CDR polling, JSON delivery, retry handling, admin controls, and CDR readiness feedback.
- Kept missed-call uploads disabled by default in generated configuration and added a shared web/PHP contract fixture.
- Added the editable FreePBX module source and prepared release package version 1.2.1.

- AMINAZADI: Updated the homepage hero headline to «بدون صداسنج هیچ مرکز تماسی موثر نیست».
- AMINAZADI: Replaced the landing page's customer voice call to action with the quick demo section shown in the reference.

## 2026-10-16 — AMINAZADI

- Corrected the bronze and gold plan artwork assignment on the homepage.
- Reassigned the supplied bronze and gold illustrations to match their colors and plan names.
- Changed the homepage pricing heading to «پلن‌های مقرون بصرفه».
- Expanded the homepage privacy and deployment descriptions with organization-specific database and self-hosting details.
- Expanded the homepage access-control description with role-based permissions for relevant sections and data.
- Redesigned the homepage footer with a contact callout, phone link, trust badge placeholders, and grouped quick links.
- Displayed the footer phone number in Persian digits outside a button.
- Increased the footer phone number size.
- Added a subtle dotted pattern to the footer background.
- Added an «درباره صداسنج» heading to the footer brand section.
- Added admin settings for the footer phone number and trust badge HTML, displayed in an isolated frame.

## 2026-10-16 — AMINAZADI

- Tightened plan card spacing and enabled horizontal mobile scrolling with the next card partially visible.

## 2026-10-16 — AMINAZADI

- Replaced the homepage plan card symbols with the supplied demo, bronze, silver, and gold illustrations.

## 2026-10-16 — AMINAZADI

- Removed the «خوش آمدید» heading from the login page.

## 2026-10-16 — AMINAZADI

- Removed the login helper text «برای ورود به پنل، اطلاعات خود را وارد کنید.».

## 2026-10-16 — AMINAZADI

- Removed the «با شماره موبایل شروع کنید» prompt from phone login.

## 2026-10-16 — AMINAZADI

- Reduced the vertical spacing and padding of the login method tabs.
