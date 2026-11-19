import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../meetings/data/meeting.dart';

/// The category chosen for the meeting about to be recorded; defaults to the
/// builtin "صورت جلسه عمومی". Lives outside the screen so it survives the
/// type-picker sheet; reset once a recording has started.
typedef PendingMeetingType = ({String code, Map<String, String> values});

const _defaultPendingMeetingType = (code: kBuiltinOutputType, values: <String, String>{});

class PendingMeetingTypeNotifier extends Notifier<PendingMeetingType> {
  @override
  PendingMeetingType build() => _defaultPendingMeetingType;

  void set(PendingMeetingType value) => state = value;

  void clear() => state = _defaultPendingMeetingType;
}

final pendingMeetingTypeProvider =
    NotifierProvider<PendingMeetingTypeNotifier, PendingMeetingType>(
      PendingMeetingTypeNotifier.new,
    );
