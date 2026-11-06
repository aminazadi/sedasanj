import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
import '../features/people/presentation/person_screen.dart';
import '../features/recording/presentation/recording_screen.dart';
import '../features/settings/presentation/settings_screen.dart';
import 'shell_screen.dart';

final routerProvider = Provider<GoRouter>((ref) {
  final router = GoRouter(
    routes: [
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
        builder: (context, state) =>
            EnrollScreen(personId: state.pathParameters['id']!),
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
