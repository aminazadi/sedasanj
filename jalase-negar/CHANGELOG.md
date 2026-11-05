## 2026-11-05 — AMINAZADI

- Added automatic background updates: a WorkManager check about every 8 hours on an unmetered network, a resumable download with SHA-256, higher-versionCode and same-signing-certificate checks, and a PackageInstaller install (no confirmation on Android 12+ where the phone allows it) only at a calm moment: not recording, nothing left to upload or sync, app in the background, free space of at least twice the APK and 30% battery or charging.
- Added a one-time Persian explainer for the "install unknown apps" permission, a one-tap notification when Android still asks for confirmation, the existing browser download as the last fallback, and a quiet "updated" toast after an update.
- Fixed the app version sent when pairing, which was hard-coded to 2.0.0; it now comes from the installed package.
- Parsed `sha256`, `min_sdk` and `mandatory` from update offers and send an anonymous random install id for staged rollouts. OEM silent-install behaviour is not verified on real phones yet.
