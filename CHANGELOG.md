# Changelog

## 2026-11-25 — AMINAZADI

- Changed the Jalase-Negar release version to 1.1.9 (build 18) for the next release builds.
- Fixed Jalase-Negar iOS release dependency resolution by setting the minimum iOS version to 14.0, as required by the installed file picker plugin.
- Fixed Jalase-Negar personal accounts being blocked by the organization minute ledger: `create_session` and `finish` no longer reserve or settle minutes for `product='jalase_negar'`, so a free account keeps working while its token budget lasts. The 402 message is Persian and points to «پلن و مصرف»; buying an hour pack now matches what the app shows.
- Fixed badges being awarded only when the progress screen was opened: meetings and documents now evaluate badges when they finish, progress is read-only, new badges get a push and a one-time notice, and `POST /v1/jalase-negar/progress/seen` records that the notice was shown. Gift grants are idempotent (`token_grants.source_id` plus a partial unique index), XP is recorded in `jalase_xp_events` so deleting a meeting does not lower the level, only complete meetings count, streaks use Saturday-start Tehran weeks with a threshold-based window, and a deactivated badge stays visible to the people who earned it.
- Fixed organization device keys reaching personal-only Jalase-Negar endpoints: `/progress`, `/invite`, `/usage` and `/plans` now return 403 for a non-personal tenant. Importing meetings into an organization now copies minutes, speakers and attendees; deleting a personal account also removes voiceprints, speaker profiles, badges, XP events, token grants, invite codes and push installations, and uses the tenant database scope when it is enabled.
- Added owner deletion for personal meetings (`DELETE /v1/jalase-negar/meetings/{id}`) that releases credit and removes audio, segments, minutes and documents, plus a worker sweep that cancels abandoned `receiving` meetings after `meeting_abandoned_after_hours` and frees their reservation. Invite settlement locks the redemption row and pays once; invite codes of deleted accounts no longer redeem.
- Added migration `0162_jalase_meeting_delete_help` with the help article «حذف جلسه و آزاد شدن اعتبار» and the `ingest_abandoned` error page.

## 2026-11-22 — AMINAZADI

- Fixed the assistant socket taking a long time to connect (or never connecting): the API container ran uvicorn with `--workers 2`, but Socket.IO/Engine.IO keeps session state per process and the proxy has no sticky routing, so polling and websocket upgrades landed on a worker that did not know the session and failed with `Invalid session`. The API now runs with `--workers 1` (`sedasanj/deploy/Dockerfile.api`). Test: `sedasanj/tests/test_api_container_workers.py`. API HTTP capacity per container is halved; scale horizontally or add sticky routing if that becomes a bottleneck.

- Replaced the Vazirmatn UI font with Yekan Bakh (Fontiran) across the admin and client panels, the FreePBX module UI, the Issabel admin styles, the aiservice dashboard, the assistant PDF/XLSX exports and the Jalase-Negar app. Fonts now load only from bundled files (the aiservice dashboard no longer loads a font from a CDN; it is served from `/admin/fonts/*`). The license code and `FontLicense.txt` placeholder must be completed before public release.

- Added an OS-level app lock to Jalase-Negar (settings → «نسخه اپ» → «قفل امنیتی برنامه»): when on, the whole app locks the instant it leaves the foreground (`AppLifecycleState.paused`) and shows a lock screen that asks the device's own fingerprint/Face ID, falling back automatically to the phone's own PIN/pattern/password (`local_auth`, `biometricOnly: false`, `stickyAuth: true`) — the app never builds its own PIN screen. A `GoRouter` top-level redirect (`lib/app/router.dart`) driven by a runtime-only `appLockRuntimeProvider` (never persisted) sends every route to the new `/lock` screen while locked; the lock preference itself (`appLockEnabledProvider`) is a plain settings flag. Turning the switch on requires one successful authentication first, so the user can't lock themselves out of their own app by mistake; the switch is greyed out with an explanation (`lib/features/app_lock/presentation/app_lock_settings_card.dart`) when the device has neither biometrics nor a screen lock configured, and the lock auto-disables itself if the device's screen lock is later removed instead of trapping the user outside the app. Android's `MainActivity` now extends `FlutterFragmentActivity` instead of `FlutterActivity` (required by `local_auth`'s `BiometricPrompt`) and declares `USE_BIOMETRIC`; iOS adds `NSFaceIDUsageDescription`. Tests: `jalase-negar/test/app_lock_test.dart` (fake `AppLockService`, no real biometric channel exercised — the device-lock prompt itself was not verified on a physical phone or simulator).

- Updated the Jalase-Negar interactive tour (`راهنمای تعاملی`), which still described screens from before the recording flow's redesign: removed the "انتخاب میکروفون" step's instructions for a manual microphone-picker button that no longer exists (microphones are now combined automatically; per-channel mute/owner assignment happens during recording instead), removed the "متن زنده" step's instructions to turn on a caption icon that no longer exists (live transcript now starts automatically once models are installed), and added a new `setup` step introducing the pre-recording "حاضران جلسه"/"نوع خروجی درخواستی" card. Also fixed the "ارسال و ساخت صورت‌جلسه" step's spotlight never appearing: the settings screen's tab split (`settings_screen.dart`) left the upload switch on a non-default tab with no way for the tour to select it; `SettingsScreen` now owns its own `TabController` and jumps to the right tab for the step it's spotlighting. Matching one-line fix in the first-run intro slides (`intro_screen.dart`)'s identical stale caption-icon claim. Tests: `jalase-negar/test/tour_test.dart` (new `setup` step, diamond-button finder fixed from a stale `Icons.mic` lookup, added a regression check that the upload switch's tab is actually built during its tour step).
- Fixed two more Jalase-Negar tour steps: the new `setup` step (previous bullet) had no spotlight target at all, so its tooltip panel defaulted to the bottom of the screen and sat on top of the very "حاضران جلسه" card it was meant to explain; `TourTarget` now wraps that card and the panel is pinned to the top (`panelAtTop: true`), matching the "recording"/"meetings" steps. The `models` step pointed at the standalone "مدل‌های هوش مصنوعی" screen (`/models`), a page most users never open directly, instead of the "مدل‌ها" tab already built into settings; it now routes to `/settings` and `SettingsScreen` switches to that tab like it already does for `connection`/`upload`, and the spotlight moved from the screen's app-bar title onto the install-status block itself (icon + "نصب و فعال است"/"دانلود، نصب و فعال‌سازی"), which both the standalone screen and the settings tab share via `ModelsBody`. Tests: `jalase-negar/test/tour_test.dart` (setup step's card tap, models step's settings-tab build and status-text tap).

## 2026-11-20 — AMINAZADI

- Replaced the Jalase-Negar login screen's hand-drawn hero illustration (`assets/images/brand/phone-signin.svg`) with the same three step illustrations the صداسنج web panels already use for phone sign-in (`sedasanj/web/client/src/assets/phone-auth-{dialog,otp,organization}.webp`, copied in at their 768w size as `jalase-negar/assets/images/brand/phone-auth-{dialog,otp,organization}.webp`), swapped per step (mobile/code/name) instead of showing one static image throughout. Dropped the now-unused `flutter_svg` import from `login_screen.dart`. Tests: `jalase-negar/test/login_screen_test.dart` (updated to expect `Image` instead of `SvgPicture`).
- Fixed the Jalase-Negar header's labelled action button (`SsAppBarAction`, e.g. "افزودن فرد" on the people tab): it drew as an outlined/filled chip at a bespoke 34px height instead of the app's plain, borderless action style; dropped the `side`/`backgroundColor`/`shape` overrides and raised `minimumSize` to 48px, matching the standard 48×48 icon-only AppBar button measured via `tester.getRect` (`jalase-negar/lib/app/widgets/ss_widgets.dart`). Tests: `jalase-negar/test/bottom_navigation_test.dart` (now also asserts the button's height matches the hamburger button's and that its style carries no border/fill).
- Fixed every Jalase-Negar header's leading button (the hamburger, and a sub-screen's back arrow) sitting flush against the screen edge — no gap at all, unlike the actions side. `SsAppBar` (`jalase-negar/lib/app/widgets/ss_widgets.dart`) now wraps whatever ends up in `leading` (an explicit widget like `shell_screen.dart`'s `DrawerButton`, or the implicit back/close button Flutter would otherwise generate — now built by a new `_SsLeadingGap` instead, so it can be wrapped too) in the same standard 16px edge gap the actions side already got, raising `leadingWidth` from 48 to 64 to fit it; a `Center` is added back by hand around the button, since `AppBar`'s own M3 code only re-centers a leading widget that is still directly an `IconButton`, which stops being true once it's wrapped. `AppBarTheme.leadingWidth` was dropped from `theme.dart` (now dead, since every `AppBar` goes through `SsAppBar`, which always sets its own). Tests: `jalase-negar/test/bottom_navigation_test.dart` (hamburger position), `jalase-negar/test/widget_test.dart` (a lone back button on a screen that never touched `leading` itself).

## 2026-11-19 — AMINAZADI

- Added a real dark theme to the Jalase-Negar app and a three-way appearance switch ("روشن"/"تاریک"/"سیستم", `ThemeModeCard` now in the settings "حساب" tab, backed by `themeModeProvider`/`ThemeModeNotifier` persisting to the same key-value `settings` table `CpuBudgetNotifier` already uses; the old "برنامه" tab, now holding only the update/push cards, was renamed "نسخه اپ"). `SsColors` (`jalase-negar/lib/app/theme.dart`) changed from a set of static light-only constants to a `ThemeExtension<SsColors>` with a tuned `SsColors.light`/`SsColors.dark` pair (the dark palette brightens the brand green, danger, success and warning tones and uses a warm near-black canvas, so brand colors stay legible rather than just inverting); `buildAppTheme` now takes a `Brightness` and builds either `ColorScheme`. Every one of the ~35 files that read a color off `SsColors` now resolves it per-frame through `SsColors.of(context)` instead of a compile-time constant, so the whole app repaints correctly when the mode changes; the handful of `CustomPainter`/`RenderProxyBox` classes that have no `BuildContext` (the bottom bar's `_BarPainter`, the waveform and voiceprint-ring painters, the QR scanner's frame painter, the onboarding tour's spotlight) now take their colors as constructor fields threaded in from the widget that builds them, rather than reading the theme themselves. A few screens (the Jalali date picker dialog, the transcript editor's text field, the SedaSanj-intro sheet, several `SsCard`s and popup menus) had a literal `Colors.white` background that would have stayed white in dark mode; those now follow the theme's canvas color. The wordmark (`SsBrandLogo`, header/drawer/splash) now draws in white in dark mode instead of its fixed near-black ink (`ssBrandLogoColor`). The diamond record/pause/stop button's icon (`SsDiamondButton`) and the bottom bar's floating record glyph were reading `SsColors.of(context).canvas` as a stand-in for "white icon on a colored diamond", which broke once canvas itself went dark; both are now a fixed `Colors.white`, like the diamond's own green/red gradient and sheen highlight, which were already theme-fixed on purpose. Tests: `jalase-negar/test/theme_mode_test.dart`; full existing suite (502 tests) still passes.
- Polished the Jalase-Negar bottom navigation bar: the floating record button now shows the hand-drawn mic glyph instead of a generic "+" (matching its "ضبط جلسه" action and the rest of the bar's icon set); both the diamond button and the bar's V-shaped notch got rounded corners (`_BarPainter._roundedPolyline` rounds the notch's three interior vertices); the active tab's soft pill now wraps its icon and label together instead of just the icon, popping in with an overshoot animation (`AnimatedContainer` + `Curves.easeOutCubic`); each glyph (`_GlyphPainter`) now draws itself in stroke-by-stroke via `Path.computeMetrics` whenever its tab becomes active, instead of appearing instantly; the gap between a nav icon and the notch was brought close to the gap between two nav icons by trimming `_slotWidth` from 132 to 116 (kept just above the notch's own 108px width); the pill's corners were sharpened from a 16px to an 8px radius; and a label like "تنظیمات" that doesn't fit its cell on a narrow screen now shrinks to fit (`FittedBox(fit: BoxFit.scaleDown)`) instead of getting clipped to "تنظیما"; and the active tab's pill is now a fixed 68px wide instead of hugging its own label, so it's the same size on every tab instead of visibly widening for a long label ("تنظیمات") and narrowing for a short one ("افراد"); and it got an explicit 6px top/bottom margin so it no longer sits flush against the nav bar's own top and bottom edges. Tests: `jalase-negar/test/bottom_navigation_test.dart`.
- Rounded the corners of the Jalase-Negar recording screen's diamond buttons (`_DiamondButton` in `recording_screen.dart`, used for start/pause/resume/stop) to the same 12px radius as the bottom bar's own record diamond, so all of them read as the same control. Tests: `jalase-negar/test/recording_screen_test.dart`.
- Restored a sign-in icon button to the Jalase-Negar meetings header (dropped when the search feature took over its action slot): a plain icon button (not the bordered icon+label style used for "افزودن فرد") while signed out, replaced by the account avatar once a connection is paired. Also moved the search field's close button from the header's leading slot to its actions side, opposite the search/filter icons it replaces. Tests: `jalase-negar/test/bottom_navigation_test.dart`, `jalase-negar/test/meetings_search_filter_test.dart`.
- Gave the Jalase-Negar app's header (`SsAppBar` in `ss_widgets.dart`) the same bottom drop shadow the bottom nav bar already paints on its own edge (plus the existing `SsColors.line` border), so the two bars read as a matching pair; also gave the meetings list's "نصب مدل‌های رونویسی" prompt card a top margin so it no longer sits flush against the header.
- Redesigned the Jalase-Negar recording screen's "no live text" state (`_EmptyHint` in `live_transcript_panel.dart`): instead of a plain line of grey text, it now leads with a short "فقط ضبط صدا" headline and a custom illustration (`assets/images/brand/audio-only-recording.svg`: a mic drawn at the same proportions as the record button's own glyph, with sound ripples and a live waveform in green, over two grey lines of "transcript" struck through), with the existing note (which still names the fix, e.g. installing the models) as the description underneath. Tests: `jalase-negar/test/live_transcript_panel_test.dart`.

- Fixed AI transcript correction having no visible effect on local (non-NineRouter) text models: llama-cpp-python 0.3.16 only compiles `response_format` into a constraining grammar for type `json_object`, so the strict per-segment `json_schema` the correction pipeline relies on (`_segment_schema` in `aiservice/asr_service/services/text_processing.py`) was silently unenforced for local GGUF models, letting the model decode unconstrained and fall through to the uncertain-marking plain-text fallback for every segment. `text_processing.process()` now compiles that schema into an explicit `grammar` before the local `create_chat_completion` call so decoding is actually constrained. Tests: `aiservice/tests/test_text_processing.py` (`LocalGrammarEnforcementTests`).
- Added a hamburger menu next to the Jalase-Negar app's logo, also reachable by swiping in from the screen edge (Flutter's built-in drawer gesture); for now it only offers "Share app". The button keeps the app's standard AppBar icon-button size; only the AppBar's titleSpacing was trimmed so it sits close to the logo instead of leaving a wide gap. Tests: `jalase-negar/test/bottom_navigation_test.dart`.
- Redesigned the Jalase-Negar login screen (mobile → OTP → name): a dotted canvas background, the app's existing `meeting-recording.svg` brand illustration as a hero image, a bordered 6-box OTP field (backed by a real, invisible `TextField` so `AutofillHints.oneTimeCode` SMS autofill still works), a "ویرایش شماره" link back to the mobile step, a bordered error banner, and a busy spinner in the primary button; the fields are no longer nested inside an extra bordered card (they already draw their own border), the heading is "ورود یا ثبت‌نام" with a shorter subtitle, and the back button got edge padding instead of sitting flush in the corner. Tests: `jalase-negar/test/login_screen_test.dart`.
- Fixed back buttons across the Jalase-Negar app rendering a bulkier, adaptive chevron (`arrow_back_ios_new`) on iOS/macOS instead of the standard arrow: `ThemeData.actionIconTheme.backButtonIconBuilder` in `jalase-negar/lib/app/theme.dart` now pins `Icons.arrow_back` everywhere, regardless of platform. Tests: `jalase-negar/test/login_screen_test.dart`.
- Removed the "دانلود مدل‌ها" header button from the Jalase-Negar meetings screen; it now shows only as a meeting-card-styled prompt above the list while the transcription models are not fully installed and active, and the same screen is also reachable as a new "مدل‌ها" tab in Settings (`ModelsBody`, extracted from `ModelsScreen` so both places share it). The settings `TabBar` was made scrollable since a 4th fixed-width tab started clipping the "ضبط و ارسال" label on narrow phones. Tests: `jalase-negar/test/meetings_models_prompt_test.dart`, `jalase-negar/test/settings_tabs_test.dart`, `jalase-negar/test/bottom_navigation_test.dart`.
- Moved the Jalase-Negar meetings screen's search field and status filter out of their own row and into the shell header as plain icon buttons (search, filter); tapping search turns the whole header into the text field (closing it returns to the logo and icon buttons), and the filter stays a popup menu. The search/filter state moved from local screen state into `meetingsSearchProvider` (`meetings_search_controller.dart`) since the header lives in `ShellScreen` while the list lives in `MeetingsScreen`, two different widget trees. (The "ورود"/account-avatar header action from the change above was pulled back out for now, pending a follow-up icon-button design for it.) Also fixed the two in-progress recording screen's diamond buttons ("توقف موقت"/"ادامه" and "پایان و ذخیره") rendering smaller (`half: 34`) than the "شروع ضبط" and bottom-bar record diamonds (`half: 38`); both now use the same `half: 38` standard size, with the gap between them narrowed instead. Tests: `jalase-negar/test/meetings_search_filter_test.dart`, `jalase-negar/test/bottom_navigation_test.dart`, `jalase-negar/test/recording_screen_test.dart`.
- The Jalase-Negar header and bottom nav now hide on scroll-down and reappear on scroll-up, on every tab under the shell (`ShellScreen` in `shell_screen.dart`): a short scroll (8px in one direction) commits to a smooth, eased 260ms transition rather than tracking the finger 1:1, so even a brief scroll plays the whole thing. The header collapses upward (`_HidingAppBar`, a `PreferredSizeWidget` wrapping the real `AppBar` in a fixed-size `OverflowBox`/`ClipRect` so Scaffold reflows around it without ever relaying out the `AppBar` itself, keeping it pixel-identical at rest); the bottom bar's chrome slides down behind the content it already extends behind (`_HidingBottomBar`); the record button detaches from the bar and migrates left with a modest, fixed drop and one full smooth turn, landing upright (`_FloatingRecordButton`; a drop sized to the slot's own slack was dropped for a small fixed `_floatDrop` instead — the diamond is large enough that a deeper drop started ducking under scrolled content rather than floating clear above it), and lives in a `Stack` above the whole `Scaffold` rather than inside its body — `Scaffold` always paints `bottomNavigationBar` above `body`, so from inside the body the button was hit-test-blocked by the (now button-less, but still fully hit-testable) bar chrome sitting above it. `RepaintBoundary`s isolate all three from the scrolling page's own compositing so scrolling itself is never disturbed. Went through two follow-up fixes to `_onScroll` before landing on the final rule. First, excluding all out-of-range (overscroll) notifications — meant to keep a pull-to-refresh tug from hiding the bars — turned out to strand the bars hidden for good on any page too short to really scroll, since every drag there is immediately out of range. Excluding only updates with no `dragDetails` (i.e. not driven by an active finger) fixed that, but then broke scrolling almost everywhere else: most real scrolling is a flick-and-release, and most of a fling's distance plays out as driver-less momentum after the finger lifts, so that version barely reacted to scrolling at all. The rule that actually holds: ignore an update only when it has *both* no `dragDetails` *and* `metrics.outOfRange` — a list snapping itself back from an overscroll once the finger's already gone. Normal fling momentum (in range, no `dragDetails`) and a deliberate drag that's entirely overscroll (out of range, real `dragDetails`, the short-page case) both still count. Tests: `jalase-negar/test/header_bottom_bar_scroll_hide_test.dart`, `jalase-negar/test/bottom_navigation_test.dart`.
- Jalase-Negar now asks which category ("نوع جلسه") to convert a meeting into before recording starts, instead of always sending it to صداسنج as صورت‌جلسه: a new picker on the idle recording screen (`_MeetingTypeSelector`/`meeting_type_picker_sheet.dart`) lists every category the admin published, with the builtin "صورت جلسه عمومی" pinned first and selected by default. The choice (`Meeting.outputTypeCode`/`outputTypeInputValues`, `app_database.dart` schema v14) rides along with the upload (`ApiClient.createSession`'s new `output_type`/`output_type_input_values`), so the server knows which category to generate without a separate manual step afterward. Tests: `jalase-negar/test/meeting_type_picker_test.dart`, `jalase-negar/test/upload_queue_test.dart`.

## 2026-11-08 — AMINAZADI

- Added a Persian design wiki in `docs/design-wiki/` (public pages, client panel, admin panel, Jalase-Negar app, design-system brief, user journeys, sample data) as input for building redesign prototypes.

## 2026-11-06 — AMINAZADI

- Added the CED audio-tagging model to the Jalase-Negar model downloads for on-device sound detection; Jalase-Negar now writes laughter, crying, coughs and similar sounds inside the speech line (calibrated on labelled clips, see `jalase-negar/docs/asr-benchmark.md`).
- Fixed Jalase-Negar voice sample recording being interrupted when the people list refreshes during synchronization.

- Added persistent, resumable public hosting of Jalase-Negar model files and one-time upstream downloads during deployment.

## 2026-11-05 — AMINAZADI

- Fixed SS-SVC-0001 `worker_failed` at `stage=decode_audio` for multi-minute calls: the Sherpa CUDA worker now decodes audio in chunks of at most 30 s (`ASR_SHERPA_GPU_CHUNK_SECONDS`) cut at quiet points instead of one whole-file decode, and failure messages include the worker exception type (`exception=`) and recognize ONNX Runtime allocation failures as `cuda_out_of_memory`.
- Changed the Jalase-Negar Android release to 1.1.2 (build 7), including the latest tab spacing, action buttons, and inline recording attendee selector.
- Added safe Sherpa CUDA failure diagnostics with worker stage, exit status, signal and recognized failure categories, including GPU OOM counter integration and troubleshooting guidance.
- Changed the Jalase-Negar Android release to 1.1.2 (build 6) with the latest integrated app changes.
- Changed the Jalase-Negar Android release to 1.0.4 (build 5), including the integrated automatic updater, People, and Guide features.
- Reworked the Jalase-Negar bottom bar into four tabs (sessions, people, settings, guide) with side insets and an active pill, added a guide screen that now holds the interactive tour and intro replay, and replaced all rounded switches with a shared square `SsSwitch`.
- Moved Jalase-Negar «افراد» into the bottom navigation, fixed the RTL direction of its list arrow, and added automatic speaker discovery: unnamed voices found in a meeting can be named once, which creates a person with voiceprints taken from that meeting's clean speech (with consent) and names all of its lines.
- Changed the Jalase-Negar Android release to 1.0.3 (build 4) and explicitly enabled v1, v2, and v3 production signing for the clean rebuild.
- Integrated the previously isolated Jalase-Negar People and Guide bottom tabs, speaker enrollment and discovery, speaker editing, and square switches into the release source.
- Fixed the Jalase-Negar header overflowing on narrow phones and added RTL navigation regression coverage for all bottom tabs and recording.
- Changed the Jalase-Negar Android release version to 1.0.2 (build 3).
- Fixed the Jalase-Negar update controller lint and translated its code comments into English.
- Fixed PBX party attribution and added an administrator review workflow for historical call ownership.
- Added extension-aware call search, export fields, and operator mapping conflict indicators.

## 2026-11-04 — AMINAZADI

- Fixed Jalase-Negar meeting lists blocked by a missing upload queue table and made the retry button restart local meeting recovery.
- Added Jalase-Negar Android release publishing and in-app update suggestions: a super-admin «نسخه‌های جلسه‌نگار» panel page (draft, notes, publish and revoke with password/TOTP confirmation, audit trail) over `/v1/admin/jalase-negar/releases`; APK checks with aapt2/apksigner (package, production certificate from `JALASE_NEGAR_APK_CERT_SHA256`, no debug/test/split, strictly higher versionCode serialised by a lock); stable codes `apk_invalid`, `apk_inspection_unavailable`, `release_version_conflict`, `release_file_unavailable` with help articles (migrations 0097/0098); a public no-store `GET /v1/jalase-negar/android/update` and range-capable download; orphan-file sweeper and a download-failure alert; and an app updater module that checks `https://api.sedasanj.ir` on every cold start without pairing, shows a Persian dialog («دریافت نسخه»/«بعداً») only on the home screen after the intro and tour, and adds «بررسی به‌روزرسانی» in Settings. Public release stays blocked until the distributed APK's certificate is confirmed as the production key.
- Added release signing for the Jalase-Negar Android build: `android/app/build.gradle.kts` reads a git-ignored `key.properties` (or `JALASE_KEY_PROPERTIES`) kept outside the repository and falls back to the debug key only when it is absent, and `JALASE_NEGAR_APK_CERT_SHA256` in `sedasanj/deploy/.env.example` now carries the public SHA-256 of the new production certificate; installs signed with the old debug key cannot update in place to this key, so they must reinstall once. The build-tools checksum (`ANDROID_BUILD_TOOLS_SHA256`) is still to be filled from Google's official `build-tools_r35` Linux archive.
- Fixed Jalase-Negar meetings that stayed marked «در حال ضبط» and were never sent to SedaSanj after recording ended: the upload queue now closes any recording the recorder no longer holds (repairing it from its WAV), the recorder wakes the queue even when the final local save fails, closed recordings can no longer keep a "recording" status, and the meetings list shows «ضبط‌شده» unless the recorder is actually open. Auto-send still follows the per-meeting send switch.
- Added an editable plain-text meeting transcript to the Jalase-Negar meeting detail screen: one line per transcript segment (the form the SedaSanj panel shows), with undo/redo, find and replace (Persian letter/digit variants match, highlighted matches, replace one or all), delete line, join with next line, character and spacing clean-up, revert, word and segment counters, and a save that keeps the timing of unchanged lines and shares time for inserted, split or joined ones (start times never decrease; lines over 4000 characters are split). Edits are saved automatically 1.2 s after typing stops (no save button, a «ذخیره شد» status instead), when the app goes to the background, and when leaving the screen; the player hides while the keyboard is open. When the meeting's text was already sent, the edit is also sent to SedaSanj after 60 s without typing, on leaving and on backgrounding (the panel text is replaced and the minutes are rebuilt once, not on every autosave); until then it is kept as pending, and if sending fails the edit stays on the phone, a notice offers «ارسال دوباره به صداسنج» (database v8 `text_sync_pending`). Rich formatting is deliberately absent because the panel renders plain segment text.
- Fixed Jalase-Negar recording completion so upload preparation failures no longer block local saving or opening the meeting details, and replaced raw finalization errors with short Persian messages.
- Added first-run intro slides to Jalase-Negar: six swipeable pages (welcome, model install, one-touch recording, live text, send to SedaSanj, ready) with animated illustrations drawn in the panel's art style (layered cards, circuit lines, waveform clusters), shown once after install before the interactive tour, with a static frame when system animations are off. Settings gained «معرفی جلسه‌نگار» to replay them (database setting `intro_slides_seen`).
- Replaced the Jalase-Negar Android and iOS launcher icons with the web panel favicon (`favicon.webp`, 64 px source, upscaled).
- Added a first-run interactive Jalase-Negar tour with live control highlights, step navigation, locally remembered dismissal, and replay from Settings.
- Shortened the Jalase-Negar final recording cue to 800 ms and showed a readiness message during playback.
- Added a three-dot menu at the end of the Jalase-Negar meeting detail app bar (opposite the title) with "ویرایش عنوان" (rename dialog) and "حذف جلسه" (confirmation, then returns to the list).
- Moved the Jalase-Negar meeting upload toggle into the section header with square corners and shortened the description of audio and transcript uploads.
- Changed Jalase-Negar to send the meeting text, which the server turns into the minutes, together with the audio, which is stored for playback in the panel and never transcribed. Added a settings switch "متن جلسه به جلسه‌نگار ارسال شود" (default on, off sends nothing; snapshotted per meeting at record start, database v7 `send_text`), a "send this meeting's text" button on the detail screen for meetings not sent or failed, and a queue that uploads audio chunks while recording, then `PUT /transcript` and `finish` once recording ends. Meetings without a transcript are not sent and the user is told how to enable live transcription; a refused audio chunk never holds back the text. Sessions an older app version opened as audio-only are not reused.
- Moved Jalase-Negar toast messages below the top toolbar, including the meeting deletion undo action.
- Added a two-second tone after the Jalase-Negar countdown and before microphone capture, and made the countdown digits bolder.
- Matched the Jalase-Negar recording header buttons and added a three-second audible countdown between the wind effect and microphone capture.
- Compacted the Jalase-Negar meeting player controls and moved the playback timer beside them below the waveform, removing the duplicate title above it.
- Removed post-recording retranscription from Jalase-Negar. Meeting details now show the saved transcript and audio player, and the meeting list no longer retries processing failures by transcribing the saved audio.
- Added live transcription to Jalase-Negar recording: a long-lived isolate runs Silero VAD on the microphone stream and decodes each finished utterance with the selected Shenava model, shows it in a live panel while recording, and saves it as a draft (ASR identity `…|segmenter:silero-vad-live`) that the full transcription replaces; live failures or a slow phone never affect the recording, and the feature can be switched off from the recording screen.
- Changed Jalase-Negar recording to disperse the illustration into windblown particles and show the PCM waveform and compact timer below the live transcript.
- Redesigned the Jalase-Negar meetings list: date-grouped sections with pinned headers, search and status filter chips, square cards with soft shadow, transcript preview, per-stage progress panel, retry on failed meetings, swipe left to delete (with undo) and right to rename, rename and audio-file share actions in the list and detail menus, skeleton loading, a recovery action on load errors, and the list now scrolls behind the bottom bar so it shows through the notch under the record button (all bottom-bar tabs share this behaviour from the shell).
- Changed the Jalase-Negar settings QR scan into a full-screen camera with a centred square scan frame (corner brackets, sweeping line, torch and close buttons); only the framed area is decoded.

## 2026-11-03 — AMINAZADI

- Made Shenava Koochik v1.5 RNNT (INT8) the recommended Jalase-Negar model, ported the platform's turn consolidation (`consolidate_segments`) and energy VAD to Dart against shared contract vectors, and recorded the segment contract fields (confidence, speaker, timestamp source, source) plus an ASR identity per meeting (database v6).
- Added a server-parity transcription mode to Jalase-Negar (server energy VAD, regions decoded as is, clips up to 30 minutes) for region-by-region comparison with the platform transcript; normal transcription still uses Silero VAD.
- Added the ASR parity contract (`sedasanj/docs/asr-parity-contract.md`) with shared fixtures for preprocessing constants, gain, transcript normalization, segment merging and the segment schema, plus server and Jalase-Negar tests that lock them; recorded the current app/server normalization gaps, including `ۀ` collapsing to a plain `ه`.
- Added `sedasanj/scripts/asr_eval.py` (stdlib WER/CER scoring and baseline comparison) and the ASR golden-set layout under `sedasanj/test_data/asr_golden/`, with audio, references and system outputs git-ignored.

- Added a fixed bottom waveform audio player (play/pause, seek, mute, speed, share) to the Jalase-Negar meeting detail screen, matching the web panel player.

- Added the shared processing indicator and installed app version to the Jalase-Negar splash screen.

- Added animated diamond pulse waves to the meeting recording start button.

- Placed the recording timer immediately below the meeting illustration.

- Added a compact, dotted meeting recording illustration inspired by the web panel artwork.

- Matched the Jalase-Negar recording screen start button size and green border to the bottom navigation button.

- Changed Jalase-Negar navigation to include a dedicated recording button and refreshed meeting and settings tabs.
- Removed the obsolete MikroTik Fadaeian Arvan setup document.
- Added Shenava Koochik v1.5 RNNT CUDA inference using FP32 encoder/decoder/joiner artifacts, preserved INT8 CPU inference, and added a model-card action to complete GPU files for existing installations with actionable missing-artifact diagnostics.
- Fixed the AI dashboard resource grid to show six cards in two rows of three on desktop, with two columns on tablets and one on phones.

## 2026-11-02 — AMINAZADI

- Added CUDA scheduling for Shenava NeMo CTC models with the pinned Sherpa CUDA 12/cuDNN 9 wheel, per-GPU isolated inference, bounded execution, CPU fallback under the existing scheduler policy, and coded worker failures.
- Replaced resource bars with live speedometer gauges, separated GPU compute from VRAM occupancy, added temperature/power/fan readings, and sampled resources independently every second with stale-data feedback and explicit network rate scales.
- Fixed AI GPU image library discovery by registering wheel-provided NVIDIA and PyTorch library paths with the system loader; added a fresh-process cuBLAS/cuDNN symbol check, regression tests, and Persian troubleshooting for SS-DEP-0001 to prevent broken GPU images from reaching inference.

## 2026-11-01 — AMINAZADI

- Redesigned the Jalase-Negar Flutter app (`jalase-negar/`) to match the SedaSanj panel: brand palette (`#F2F0EF`, `#B2AC88`, `#898989`, `#4B6E48`), zero border radius, no shadows, dotted patterns, green dotted app bar, dotted section title bands and square badges, via a new shared theme (`lib/app/theme.dart`) and widgets (`lib/app/widgets/ss_widgets.dart`). Reused the SedaSanj office line art, empty-state illustration and pattern images (`assets/images/brand/`) and the Vazirmatn variable font as static 350/500/600 instances. Verified on the Android emulator only; iOS and the lab matrix were not run.
- Removed all on-device analysis from Jalase-Negar: local LLM minutes (fllama/Dorna), transcript correction, online AI transcription, license gating and their settings; the embedded online-AI API key is gone from the source and must still be revoked by its owner. Local database migrates to version 4 (drops minutes, corrections and online transcripts) and meeting statuses now cover the upload/processing flow. Dropped unused dependencies, fonts and Android build hacks.
- Added the Jalase-Negar SedaSanj connection flow: pairing payload parser (`sedasanj.jalase-negar.config` v1, expiry and https checks), typed `ApiClient` with Persian actionable errors (401 reconnect, 402 top-up, pairing/limit codes), token kept in secure storage, and a connection screen with QR scan, config file and pasted-config import plus disconnect. Added camera permission for QR scanning.
- Reworked Jalase-Negar recording (J3): mono 16 kHz capture with a microphone foreground service, sample-based timing, 45–90 s WAV chunks cut at silence and registered in a new `upload_chunks` table (DB v5), meeting row written at start so killed recordings are repaired and recovered on next launch, disk-space guard (500 MB), and surfacing of OS interruptions. Added chunk writer and WAV repair tests.
- Added the Jalase-Negar upload queue (J5): chunks are uploaded while the meeting is still recording (two at a time, sha256-verified, exponential backoff with jitter), the session is created idempotently and resumed from the server's received chunks, finished once every chunk is in, then server processing is followed to completion. 401/402 stop the queue with Persian guidance, a server-deleted meeting is marked failed, and local chunk files are removed after the server accepts the finish. The list shows upload progress. Added `test/tools/fake_sedasanj.py` for emulator testing and queue unit tests with a fake API.


## 2026-10-31 — AMINAZADI

- Replaced the Font Awesome spinners in the FreePBX module page (version history, update download button, update progress header and the running step) with the assistant's four-square loader (`.sj-loader`), and removed the unused `.icon-spin` style from the ASR dashboard. `php -l` was not run (PHP is not installed locally).

- Released FreePBX module 1.5.5 with the existing internal-call direction mapping and synchronized release metadata; ZIP integrity passed, but PHP 7.4/8.2 tests could not run because the Docker daemon was unavailable, and PBX lab validation remains pending.

- Marked FreePBX `exten-*` recordings as `internal` in the recording hook (`mix-stereo.php`) and the ingest mapper so extension-to-extension calls reach the platform with `direction=internal`; the platform still classifies calls from the synced extension list. The `exten-` filename prefix and `php -l` under 7.4/8.x are not yet lab-confirmed (⚠ needs lab confirmation); test added to `IngestDestinationTest.php`.
- Added explicit Issabel-only installation guards, separated the module UI script, and recorded final beta validation with pending PBX lab certification.
- Added the Issabel 4/5 beta module, shared PBX engine, legacy PHP gateway, original-recording preservation, generated-dialplan adapters, verified installation backups and rollback.
- Replaced the column checkboxes in the calls export dialog with the shared `ToggleSwitch` component used elsewhere in the panel.
- Redesigned the organization dashboard around chart-only KPIs (conversion, quality and SLA gauges, daily trend, call-to-opportunity funnel, operator comparison, tasks, unanswered call types) and moved numeric cards, tables and secondary analyses into a collapsible details section stored in the `details` URL parameter; the customer-satisfaction block is unchanged.
- Fixed module log viewer overflow and added an ALL minimum-level filter.
- Fixed module 1.5.3 inbound recording direction, escaped MixMonitor filename filters, and answered-extension recovery for rejected uploads.

- Fixed missed-call labels to show a single concise status and aligned caller and destination details in the calls table.
- Documented FreePBX module licensing, third-party attribution, release-signing status, and GPL-compatible protection measures.
- Fixed FreePBX module recording hooks failing to locate answered-call audio legs when Asterisk normalizes hyphens in the post-record filename; added regression coverage.

## 2026-10-30 — AMINAZADI

- Fixed module 1.5.1 metadata causing FreePBX bootstrap to pass an array to stristr() after upload; retained coded PHP-extension checks and documented backup-first panel recovery.

- Replaced the outdated module 1.3.7 ZIP with a verified module 1.5.0 installation archive after passing PHP 7.4 and 8.2 lint and module tests; generated release archives remain outside version control.
- Added PBX extension sync from the FreePBX module: calls between two synced extensions are now recorded as internal, extension numbers show a contact, operator or PBX name, and each extension can be linked to a phonebook contact and an operator from the phonebook page (migration `0060_pbx_extensions`).

## 2026-10-29 — AMINAZADI

- Fixed the existing-organization form flashing briefly while automatic phone login completes.
- Added automatic login submission when a six-digit SMS or authenticator OTP is completed across client, organization and admin sign-in flows.
- Replaced oversized admin and client panel PNG artwork with display-sized high-quality WebP assets and deferred below-the-fold image decoding and loading.

## 2026-10-29 — AMINAZADIAN

- Hardened automatic FreePBX module updates with a signed, expiring release manifest, refusal of older releases, and support for up to three trusted keys during key rotation.
- Added module diagnostics reports (hourly doctor results) with an admin health view, the `requeue-failed` tool for recordings in `failed/`, and a CI workflow for the module (PHP 7.4 to 8.3), API and web apps.
- Fixed ASR failure classification (silence, httpx timeouts, tenant credit errors), finished dead-lettered webhooks as complete calls, stopped echoing submitted values and internal errors in API responses, and made non-5xx HTTP errors non-retryable.
- Added Alertmanager with alert rules for workers, provisioning, 5xx rates, ingest rejections and webhooks; applied no-new-privileges and dropped capabilities for the Python services.
- Agent: key/account rejections now pause calls instead of dead-lettering them, the call start time comes from the Uniqueid, delivered MixMonitor legs are removed, and ffmpeg has a timeout.
- Repaired stale tests so the full Python suite passes.

## 2026-10-29 — AMINAZADIAN

- Added the help center: staff manage articles, categories, error-code mappings and image/video media in the admin panel; readers open `/help`, and the FreePBX module links every error code to `/help/errors/<CODE>`. Article HTML is rebuilt from an allowlist, uploads are validated by content, and a seed script creates draft articles for the most common module errors.

## 2026-10-29 — AMINAZADI

- Hardened FreePBX module 1.3.9: filtered all caller-controlled MixMonitor command arguments against shell injection, added CSRF tokens and POST-only enforcement to settings save, configuration import and update start, and validated the manual settings form server-side.

## 2026-10-29 — AMINAZADI

- Rebuilt backup and restore: tenant databases, a host-side audio mirror and an encrypted secrets bundle (`.env` keys, database roles, release signing seed) are now backed up with `pg_restore --list` verification, SHA-256 checksums, atomic temp-then-rename writes, keep-last-N pruning and an optional off-host rsync target; restore now stops every writer, takes a pre-restore snapshot, restores into fresh databases swapped in by rename with `--exit-on-error --single-transaction`, re-applies role grants, requires confirmation (`--yes` to skip), and a new `restore_tenant.sh` restores a single tenant. Documented a monthly restore drill.
- Fixed recording uploads whose FreePBX destination is a nonnumeric dialplan label by using the attributed agent extension as the dialed number.
- Fixed missed-call API idempotency conflict handling to use the actual unique key columns in module ingestion.
- Fixed FreePBX global database handle corruption during CDR lookups in module 1.3.7.
- Fixed background FreePBX CDR bootstrap variable scope in module 1.3.6.
- Fixed FreePBX voicemail configuration parse-back and persisted active module tabs in the URL across all form actions in module 1.3.5.

## 2026-10-28 — AMINAZADI

- Changed FreePBX update-check and release-history error messages to English and released module 1.3.4.
- Changed the FreePBX release-history tab title to English and released module 1.3.3.
- Added a direct FreePBX custom-CDR fallback and released module 1.3.2 after field validation exposed an environment-specific include parsing failure.
- Fixed FreePBX missed-call validation to resolve effective CDR options from included configuration files and prepared module release 1.3.1.
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
