import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

class MeetingIllustration extends StatelessWidget {
  const MeetingIllustration({super.key});

  @override
  Widget build(BuildContext context) {
    return ExcludeSemantics(
      child: Center(
        heightFactor: 1,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 270),
          child: SvgPicture.asset(
            'assets/images/brand/meeting-recording.svg',
            fit: BoxFit.contain,
          ),
        ),
      ),
    );
  }
}
