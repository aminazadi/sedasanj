import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../data/app_update.dart';
import '../data/update_client.dart';
import '../data/update_environment.dart';
import 'update_background.dart';

final updateClientProvider = Provider<UpdateClient>((ref) => UpdateClient());

final updateEnvironmentProvider =
    Provider<Future<UpdateEnvironment?> Function()>(
      (ref) => readUpdateEnvironment,
    );

/// Opens a download link in the external browser; false when none could open it.
final updateLauncherProvider = Provider<Future<bool> Function(Uri)>(
  (ref) =>
      (uri) => launchUrl(uri, mode: LaunchMode.externalApplication),
);

class UpdateState {
  const UpdateState({
    this.installed,
    this.offer,
    this.dismissed = false,
    this.checking = false,
  });

  /// The running app, once the environment has been read.
  final UpdateEnvironment? installed;

  /// The newest compatible build the server offered, if any.
  final AppUpdateOffer? offer;

  /// "Later" was chosen: no more automatic prompts until the next cold start.
  final bool dismissed;
  final bool checking;

  /// An offer that should interrupt the user at the next calm moment.
  bool get pending => offer != null && installed != null && !dismissed;

  UpdateState copyWith({
    UpdateEnvironment? installed,
    AppUpdateOffer? offer,
    bool clearOffer = false,
    bool? dismissed,
    bool? checking,
  }) => UpdateState(
    installed: installed ?? this.installed,
    offer: clearOffer ? null : (offer ?? this.offer),
    dismissed: dismissed ?? this.dismissed,
    checking: checking ?? this.checking,
  );
}

/// Outcome of a check the user asked for, with a Persian message when useful.
class ManualCheckResult {
  const ManualCheckResult({this.offer, this.message});

  final AppUpdateOffer? offer;
  final String? message;
}

class UpdateController extends Notifier<UpdateState> {
  bool _launchChecked = false;
  bool _backgroundStarted = false;

  @override
  UpdateState build() => const UpdateState();

  /// Cold-start check. Never throws, never blocks, and stays silent on any
  /// failure: offline, timeout or an invalid answer simply mean "no offer".
  Future<void> checkOnLaunch() async {
    if (_launchChecked) return;
    _launchChecked = true;
    try {
      await _check();
    } on UpdateCheckException {
      // Silent by design.
    } catch (_) {
      // Silent by design.
    }
  }

  /// Check started from settings: always answers with an offer or a message.
  Future<ManualCheckResult> checkManually() async {
    if (state.checking) {
      return const ManualCheckResult(
        message: 'بررسی به‌روزرسانی در حال انجام است؛ چند لحظه صبر کنید.',
      );
    }
    try {
      final offer = await _check();
      if (offer == null) {
        return const ManualCheckResult(
          message: 'نسخه‌ی جدیدتری برای گوشی شما وجود ندارد.',
        );
      }
      // An explicit request overrides an earlier "later".
      state = state.copyWith(dismissed: false);
      return ManualCheckResult(offer: offer);
    } on UpdateCheckException catch (e) {
      return ManualCheckResult(message: e.message);
    } catch (_) {
      return const ManualCheckResult(
        message: 'بررسی به‌روزرسانی انجام نشد؛ دوباره تلاش کنید.',
      );
    }
  }

  Future<AppUpdateOffer?> _check() async {
    state = state.copyWith(checking: true);
    try {
      final environment = await ref.read(updateEnvironmentProvider)();
      if (environment == null) {
        throw const UpdateCheckException(
          'این دستگاه بررسی به‌روزرسانی را پشتیبانی نمی‌کند.',
        );
      }
      final offer = await ref.read(updateClientProvider).check(environment);
      // Only strictly newer builds are ever shown, whatever the server says.
      final usable =
          offer != null && offer.versionCode > environment.versionCode
          ? offer
          : null;
      state = state.copyWith(
        installed: environment,
        offer: usable,
        clearOffer: usable == null,
      );
      return usable;
    } finally {
      state = state.copyWith(checking: false);
    }
  }

  /// "Later": set the offer aside until the next cold start.
  void postpone() => state = state.copyWith(dismissed: true);

    try {
      if (offer.canAutoInstall &&
          await ref.read(updateNativeProvider).installDownloaded()) {
        return null;
      }
    } catch (_) {
      // Falls back to the browser below.
    }
