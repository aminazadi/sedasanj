import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/app_lock/application/app_lock_providers.dart';
import '../features/app_lock/presentation/app_lock_screen.dart';
import '../features/auth/presentation/login_screen.dart';
import '../features/guide/presentation/guide_screen.dart';
import '../features/meetings/presentation/meeting_detail_screen.dart';
import '../features/meetings/presentation/meetings_screen.dart';
import '../features/models/presentation/models_screen.dart';
import '../features/onboarding/intro/intro_progress.dart';
import '../features/onboarding/intro/intro_screen.dart';
import '../features/onboarding/permissions_screen.dart';
import '../features/onboarding/tour_overlay.dart';
import '../features/onboarding/tour_progress.dart';
import '../features/onboarding/tour_step.dart';
import '../features/people/presentation/enroll_screen.dart';
import '../features/people/presentation/new_person_screen.dart';
import '../features/people/presentation/people_screen.dart';
import '../features/plans/presentation/plans_screen.dart';
import '../features/plans/presentation/progress_screen.dart';
import '../features/people/presentation/person_screen.dart';
import '../features/recording/presentation/recording_screen.dart';
import '../features/settings/presentation/settings_screen.dart';
import 'shell_screen.dart';

final routerProvider = Provider<GoRouter>((ref) {
  final router = GoRouter(
    // Re-runs `redirect` the instant the app-lock state flips, so a resume
    // that locks the app (or a successful unlock) takes effect immediately
    // instead of waiting for the next navigation attempt.
    refreshListenable: ref.watch(appLockRuntimeProvider),
    // The bank page reopens the app with jalasenegar://payment/result; show the
    // plans screen, which re-checks the pending order by itself.
    redirect: (context, state) {
      if (ref.read(appLockRuntimeProvider).locked) {
        return state.uri.path == '/lock' ? null : '/lock';
      }
      if (state.uri.path == '/lock') return null;
      return state.uri.path == '/result' || state.uri.path == '/payment/result'
          ? '/plans'
          : null;
    },
    routes: [
      GoRoute(
        path: '/lock',
        builder: (context, state) => const AppLockScreen(),
      ),
      ShellRoute(
        builder: (context, state, child) =>
            _withTour(state, ShellScreen(child: child)),
        routes: [
          GoRoute(
            path: '/',
            redirect: (context, state) async {
              if (state.uri.queryParameters.containsKey('tour')) return null;
              if (!await ref.read(introProgressProvider.future)) {
                return '/intro';
              }
              final seen = await ref.read(tourProgressProvider.future);
              return seen ? null : TourStep.welcome.location();
            },
            builder: (context, state) => const MeetingsScreen(),
          ),
          GoRoute(
            path: '/settings',
            builder: (context, state) => const SettingsScreen(),
          ),
          GoRoute(
            path: '/guide',
            builder: (context, state) => const GuideScreen(),
          ),
          GoRoute(
            path: '/people',
            builder: (context, state) => const PeopleScreen(),
          ),
        ],
      ),
      GoRoute(
        path: '/intro',
        builder: (context, state) =>
            IntroScreen(replay: state.uri.queryParameters['replay'] == '1'),
      ),
      GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
      GoRoute(path: '/plans', builder: (context, state) => PlansScreen()),
      GoRoute(
        path: '/progress',
        builder: (context, state) => const ProgressScreen(),
      ),
      GoRoute(
        path: '/permissions',
        builder: (context, state) => const PermissionsScreen(),
      ),
      GoRoute(
        path: '/record',
        builder: (context, state) => _withTour(state, const RecordingScreen()),
      ),
      GoRoute(
        path: '/meeting/:id',
        builder: (context, state) =>
            MeetingDetailScreen(meetingId: state.pathParameters['id']!),
      ),
      GoRoute(
        path: '/people/new',
        builder: (context, state) => NewPersonScreen(
          returnPerson: state.uri.queryParameters['return'] == '1',
        ),
      ),
      GoRoute(
        path: '/people/:id',
        builder: (context, state) =>
            PersonScreen(personId: state.pathParameters['id']!),
      ),
      GoRoute(
        path: '/people/:id/enroll',
        builder: (context, state) => EnrollScreen(
          personId: state.pathParameters['id']!,
          popOnFinish: state.uri.queryParameters['return'] == '1',
        ),
      ),
      GoRoute(
        path: '/models',
        builder: (context, state) => _withTour(state, const ModelsScreen()),
      ),
    ],
  );
  ref.onDispose(router.dispose);
  return router;
});

Widget _withTour(GoRouterState state, Widget child) {
  final step = TourStep.fromUri(state.uri);
  if (step == null) return child;
  return TourOverlay(
    step: step,
    fromSettings: state.uri.queryParameters['from'] == 'settings',
    child: child,
  );
}
