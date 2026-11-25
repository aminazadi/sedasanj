/// Usage, plans, token packs, badges and invites of a personal account, as the server sends them.
library;

double _hours(Object? value) => (value as num?)?.toDouble() ?? 0;

/// "About N hours of meetings left" (real LLM tokens, shown as hours by the server).
class UsageInfo {
  const UsageInfo({
    required this.unlimited,
    this.planHours = 0,
    this.usedHours = 0,
    this.planRemainingHours = 0,
    this.bonusHours = 0,
    this.remainingHours = 0,
    this.exhausted = false,
    this.resetsAt,
  });

  factory UsageInfo.fromJson(Map<String, dynamic> json) => UsageInfo(
    unlimited: json['unlimited'] == true,
    planHours: _hours(json['plan_hours']),
    usedHours: _hours(json['used_hours']),
    planRemainingHours: _hours(json['plan_remaining_hours']),
    bonusHours: _hours(json['bonus_hours']),
    remainingHours: _hours(json['remaining_hours']),
    exhausted: json['exhausted'] == true,
    resetsAt: json['resets_at'] is String
        ? DateTime.tryParse(json['resets_at'] as String)
        : null,
  );

  final bool unlimited;
  final double planHours;
  final double usedHours;

  /// Left of this month's plan allowance.
  final double planRemainingHours;

  /// Bought or gift tokens, used after the monthly allowance.
  final double bonusHours;
  final double remainingHours;
  final bool exhausted;
  final DateTime? resetsAt;
}

class PlanInfo {
  const PlanInfo({
    required this.code,
    required this.name,
    required this.monthlyPriceToman,
    required this.monthlyHours,
    required this.buyable,
  });

  factory PlanInfo.fromJson(Map<String, dynamic> json) => PlanInfo(
    code: json['code'] as String,
    name: json['name'] as String,
    monthlyPriceToman: (json['monthly_price_toman'] as num?)?.toInt() ?? 0,
    monthlyHours: (json['monthly_hours'] as num?)?.toDouble(),
    buyable: json['buyable'] == true,
  );

  final String code;
  final String name;
  final int monthlyPriceToman;
  final double? monthlyHours;
  final bool buyable;
}

class PlansResult {
  const PlansResult({required this.free, required this.plans});

  factory PlansResult.fromJson(Map<String, dynamic> json) => PlansResult(
    free: json['free'] is Map
        ? PlanInfo.fromJson(json['free'] as Map<String, dynamic>)
        : null,
    plans: [
      for (final raw in (json['plans'] as List? ?? const []))
        PlanInfo.fromJson(raw as Map<String, dynamic>),
    ],
  );

  final PlanInfo? free;
  final List<PlanInfo> plans;
}

class PackInfo {
  const PackInfo({
    required this.id,
    required this.name,
    required this.hours,
    required this.priceToman,
  });

  factory PackInfo.fromJson(Map<String, dynamic> json) => PackInfo(
    id: json['id'] as String,
    name: json['name'] as String,
    hours: _hours(json['hours']),
    priceToman: (json['price_toman'] as num?)?.toInt() ?? 0,
  );

  final String id;
  final String name;
  final double hours;
  final int priceToman;
}

class OrderStatus {
  const OrderStatus({required this.status});

  final String status;

  bool get paid => status == 'paid';
  bool get closed => status == 'canceled' || status == 'failed';
}

class BadgeInfo {
  const BadgeInfo({
    required this.code,
    required this.title,
    required this.description,
    required this.current,
    required this.threshold,
    required this.earned,
    this.rewardTokens = 0,
    this.rewardSkipped = false,
    this.active = true,
  });

  factory BadgeInfo.fromJson(Map<String, dynamic> json) => BadgeInfo(
    code: json['code'] as String,
    title: json['title'] as String,
    description: json['description'] as String,
    current: (json['current'] as num?)?.toInt() ?? 0,
    threshold: (json['threshold'] as num?)?.toInt() ?? 1,
    earned: json['earned'] == true,
    rewardTokens: (json['reward_tokens'] as num?)?.toInt() ?? 0,
    rewardSkipped: json['reward_skipped'] == true,
    active: json['active'] != false,
  );

  final String code;
  final String title;
  final String description;
  final int current;
  final int threshold;
  final bool earned;
  final int rewardTokens;

  /// The badge was earned but the month's gift cap left no room for all of
  /// its tokens.
  final bool rewardSkipped;

  /// False for a badge the admin stopped offering; it stays listed only for
  /// people who already earned it.
  final bool active;
}

class ProgressInfo {
  const ProgressInfo({
    required this.xp,
    required this.level,
    required this.levelXp,
    required this.nextLevelXp,
    required this.streakWeeks,
    required this.badges,
    required this.newlyEarned,
    required this.giftLeftHours,
    required this.giftLimitHours,
  });

  factory ProgressInfo.fromJson(Map<String, dynamic> json) {
    final gift = (json['gift'] as Map?) ?? const {};
    final metrics = (json['metrics'] as Map?) ?? const {};
    return ProgressInfo(
      xp: (json['xp'] as num?)?.toInt() ?? 0,
      level: (json['level'] as num?)?.toInt() ?? 1,
      levelXp: (json['level_xp'] as num?)?.toInt() ?? 0,
      nextLevelXp: (json['next_level_xp'] as num?)?.toInt() ?? 25,
      streakWeeks: (metrics['streak_weeks'] as num?)?.toInt() ?? 0,
      badges: [
        for (final raw in (json['badges'] as List? ?? const []))
          BadgeInfo.fromJson(raw as Map<String, dynamic>),
      ],
      newlyEarned: [
        for (final raw in (json['newly_earned'] as List? ?? const []))
          (raw as Map)['title'] as String,
      ],
      giftLeftHours: _hours(gift['left_hours']),
      giftLimitHours: _hours(gift['limit_hours']),
    );
  }

  final int xp;
  final int level;
  final int levelXp;
  final int nextLevelXp;
  final int streakWeeks;
  final List<BadgeInfo> badges;

  /// Titles of badges this very request awarded (to celebrate once).
  final List<String> newlyEarned;
  final double giftLeftHours;
  final double giftLimitHours;

  double get levelFraction {
    final span = nextLevelXp - levelXp;
    return span <= 0 ? 1 : ((xp - levelXp) / span).clamp(0.0, 1.0);
  }
}

class InviteInfo {
  const InviteInfo({
    required this.code,
    required this.joined,
    required this.rewardHours,
    required this.enabled,
  });

  factory InviteInfo.fromJson(Map<String, dynamic> json) => InviteInfo(
    code: json['code'] as String,
    joined: (json['joined'] as num?)?.toInt() ?? 0,
    rewardHours: _hours(json['reward_hours']),
    enabled: json['enabled'] == true,
  );

  final String code;
  final int joined;
  final double rewardHours;
  final bool enabled;
}
