import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Client ids of the people chosen as present before recording starts. Lives
/// outside the screen so it survives the new-person page; cleared once a
/// recording has started.
class PendingAttendees extends Notifier<Set<String>> {
  @override
  Set<String> build() => const {};

  void set(Set<String> ids) => state = {...ids};

  void remove(String id) => state = {...state}..remove(id);

  void clear() => state = const {};
}

final pendingAttendeesProvider =
    NotifierProvider<PendingAttendees, Set<String>>(PendingAttendees.new);
