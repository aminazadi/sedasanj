import 'dart:math';
import 'package:flutter/material.dart';

import '../../../app/theme.dart';
import '../../../app/widgets/ss_widgets.dart';

class TeamScreen extends StatelessWidget {
  const TeamScreen({super.key});

  static const List<TeamMember> members = [
    TeamMember(
      name: 'محمد امین آزادیان',
      imagePath: 'assets/images/team/azadian.jpg',
      description: 'توسعه‌دهنده ارشد',
    ),
    TeamMember(
      name: 'فرهاد ستوده',
      imagePath: 'assets/images/team/sotoudeh.jpg',
      description: 'توسعه‌دهنده بک‌اند و زیرساخت',
    ),
    TeamMember(
      name: 'احسان ظفر',
      imagePath: 'assets/images/team/zafar.jpg',
      description: 'مدیر محصول',
    ),
    TeamMember(
      name: 'سعید شیعه',
      imagePath: 'assets/images/team/shia.jpg',
      description: 'مدیر فروش',
    ),
    TeamMember(
      name: 'عرفان ظفر',
      imagePath: 'assets/images/team/erfan.jpg',
      description: 'توسعه‌دهنده هوش مصنوعی و پردازش زبان',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rng = Random(42);
    final shuffled = List<TeamMember>.from(members)..shuffle(rng);

    return Scaffold(
      appBar: SsAppBar(title: const Text('تولیدکنندگان'), centerTitle: true),
      body: LayoutBuilder(
        builder: (context, constraints) {
          return SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: ConstrainedBox(
              constraints: BoxConstraints(minHeight: constraints.maxHeight),
              child: Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const SsPageHeader(
                      title: 'تیم روبولینک',
                      description: 'تولیدکنندگان نرم‌افزار جلسه‌نگار',
                    ),
                    const SizedBox(height: 24),
                    _TeamGallery(members: shuffled),
                    const SizedBox(height: 32),
                    Text(
                      'نسخه ۰.۱.۰ (آزمایشی)',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '© ۱۴۰۵ تیم روبولینک',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class TeamMember {
  const TeamMember({
    required this.name,
    required this.imagePath,
    required this.description,
  });

  final String name;
  final String imagePath;
  final String description;
}

class _TeamGallery extends StatelessWidget {
  const _TeamGallery({required this.members});

  final List<TeamMember> members;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      alignment: WrapAlignment.center,
      spacing: 12,
      runSpacing: 12,
      children: [for (final m in members) _MemberTile(member: m)],
    );
  }
}

class _MemberTile extends StatelessWidget {
  const _MemberTile({required this.member});

  final TeamMember member;

  Widget _photo(double size) => Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      color: SsColors.selected,
      border: Border.all(color: SsColors.accent),
    ),
    child: Image.asset(
      member.imagePath,
      fit: BoxFit.cover,
      errorBuilder: (_, __, ___) => Stack(
        alignment: Alignment.center,
        children: [
          const Positioned.fill(child: SsDots()),
          Icon(Icons.person, size: size * 0.45, color: SsColors.neutral),
        ],
      ),
    ),
  );

  void _showDetail(BuildContext context) {
    final theme = Theme.of(context);
    showDialog(
      context: context,
      builder: (ctx) => Dialog(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _photo(112),
              const SizedBox(height: 16),
              Text(
                member.name,
                style: theme.textTheme.titleMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                member.description,
                style: theme.textTheme.bodySmall,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 16),
              TextButton(
                onPressed: () => Navigator.of(ctx).pop(),
                child: const Text('بستن'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SsCard(
      padding: const EdgeInsets.all(8),
      onTap: () => _showDetail(context),
      child: SizedBox(
        width: 96,
        child: Column(
          children: [
            _photo(96),
            const SizedBox(height: 8),
            Text(
              member.name,
              maxLines: 2,
              textAlign: TextAlign.center,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelMedium,
            ),
          ],
        ),
      ),
    );
  }
}
