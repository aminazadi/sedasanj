import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shamsi_date/shamsi_date.dart';

import '../data/meeting.dart';

enum MeetingFilter {
  all('همه'),
  active('در حال پردازش'),
  complete('کامل'),
  failed('ناموفق');

  const MeetingFilter(this.label);

  final String label;

  bool accepts(Meeting m) => switch (this) {
    MeetingFilter.all => true,
    MeetingFilter.active =>
      m.status != MeetingStatus.complete && m.status != MeetingStatus.failed,
    MeetingFilter.complete => m.status == MeetingStatus.complete,
    MeetingFilter.failed => m.status == MeetingStatus.failed,
  };
}

/// The meetings list's search box and status filter; owned here (instead of
/// locally in the meetings screen) because the search box itself lives in
/// the app shell's header, not in the meetings screen's body.
class MeetingsSearchState {
  const MeetingsSearchState({
    this.active = false,
    this.query = '',
    this.filter = MeetingFilter.all,
    this.date,
  });

  /// Whether the header has turned into the search field.
  final bool active;
  final String query;
  final MeetingFilter filter;

  /// Set from the "jump to date" calendar; narrows the list to meetings
  /// recorded on this Jalali day. Null means no date filter.
  final Jalali? date;

  MeetingsSearchState copyWith({
    bool? active,
    String? query,
    MeetingFilter? filter,
    Jalali? date,
    bool clearDate = false,
  }) => MeetingsSearchState(
    active: active ?? this.active,
    query: query ?? this.query,
    filter: filter ?? this.filter,
    date: clearDate ? null : (date ?? this.date),
  );
}

class MeetingsSearchController extends Notifier<MeetingsSearchState> {
  @override
  MeetingsSearchState build() => const MeetingsSearchState();

  void open() => state = state.copyWith(active: true);

  /// Collapses the header back to its normal state; the status filter (not
  /// tied to the text box) is left as the user set it.
  void close() => state = state.copyWith(active: false, query: '');

  void setQuery(String value) => state = state.copyWith(query: value);

  void setFilter(MeetingFilter filter) =>
      state = state.copyWith(filter: filter);

  void setDate(Jalali date) => state = state.copyWith(date: date);

  void clearDate() => state = state.copyWith(clearDate: true);

  void clear() => state = state.copyWith(
    query: '',
    filter: MeetingFilter.all,
    clearDate: true,
  );
}

final meetingsSearchProvider =
    NotifierProvider<MeetingsSearchController, MeetingsSearchState>(
      MeetingsSearchController.new,
    );
