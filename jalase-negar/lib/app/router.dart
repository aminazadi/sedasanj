import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/meetings/presentation/meeting_detail_screen.dart';
import '../features/meetings/presentation/meetings_screen.dart';
import '../features/models/presentation/models_screen.dart';
import '../features/recording/presentation/recording_screen.dart';
import '../features/settings/presentation/settings_screen.dart';
import '../features/team/presentation/team_screen.dart';
import 'shell_screen.dart';

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    routes: [
      ShellRoute(
        builder: (context, state, child) => ShellScreen(child: child),
        routes: [
          GoRoute(
            path: '/',
            builder: (context, state) => const MeetingsScreen(),
          ),
          GoRoute(
            path: '/settings',
            builder: (context, state) => const SettingsScreen(),
          ),
        ],
      ),
      GoRoute(
        path: '/record',
        builder: (context, state) => const RecordingScreen(),
      ),
      GoRoute(
        path: '/meeting/:id',
        builder: (context, state) =>
            MeetingDetailScreen(meetingId: state.pathParameters['id']!),
      ),
      GoRoute(
        path: '/models',
        builder: (context, state) => const ModelsScreen(),
      ),
      GoRoute(path: '/team', builder: (context, state) => const TeamScreen()),
    ],
  );
});
