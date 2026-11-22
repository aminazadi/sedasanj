import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Brand/semantic colors, resolved per [Brightness]. Shared tokens with the
/// SedaSanj web panel (shared/theme.js, index.css) keep their light values;
/// each also carries a dark-mode counterpart tuned for contrast on a dark
/// canvas. Access the resolved set with `SsColors.of(context)`.
@immutable
class SsColors extends ThemeExtension<SsColors> {
  const SsColors({
    required this.canvas,
    required this.accent,
    required this.neutral,
    required this.primary,
    required this.primaryDark,
    required this.primaryLight,
    required this.selected,
    required this.ink,
    required this.danger,
    required this.success,
    required this.warning,
    required this.line,
    required this.lineStrong,
  });

  /// Page/card background. The app's flat, bordered design uses one surface
  /// tone everywhere, so this is also the card and sheet background.
  final Color canvas;

  /// Secondary brand accent (olive/gold): decorative icons, QR frame, the
  /// waveform's secondary bars.
  final Color accent;

  /// Secondary text, inactive icons, subtitles.
  final Color neutral;

  /// Main interactive brand color: buttons, headings, active icons.
  final Color primary;

  /// Emphasis text/icon drawn on a [selected] background (onPrimaryContainer).
  final Color primaryDark;

  /// Lighter tint of [primary]; rarely used on its own.
  final Color primaryLight;

  /// Tinted background for a selected/active chip, tab or row.
  final Color selected;

  /// Primary text color.
  final Color ink;

  final Color danger;
  final Color success;
  final Color warning;

  /// Subtle divider/border (accent-tinted).
  final Color line;

  /// Stronger divider/border (neutral-tinted).
  final Color lineStrong;

  static const light = SsColors(
    canvas: Color(0xFFF2F0EF),
    accent: Color(0xFFB2AC88),
    neutral: Color(0xFF898989),
    primary: Color(0xFF4B6E48),
    primaryDark: Color(0xFF3E5C3B),
    primaryLight: Color(0xFF4F7A4C),
    selected: Color(0xFFE7ECDD),
    ink: Color(0xFF334155),
    danger: Color(0xFFBE123C),
    success: Color(0xFF5F805B),
    warning: Color(0xFF9C9678),
    // rgb(178 172 136 / 0.5)
    line: Color(0x80B2AC88),
    // rgb(137 137 137 / 0.5)
    lineStrong: Color(0x80898989),
  );

  static const dark = SsColors(
    canvas: Color(0xFF1A1917),
    accent: Color(0xFFC9C29A),
    neutral: Color(0xFFA6A6A6),
    primary: Color(0xFF5FA05A),
    // Light mint: text/icons on the dark-tinted [selected] background.
    primaryDark: Color(0xFFBFE2B9),
    primaryLight: Color(0xFF7BBF76),
    selected: Color(0xFF223027),
    ink: Color(0xFFEDEBE6),
    danger: Color(0xFFFF6B85),
    success: Color(0xFF7FBF78),
    warning: Color(0xFFD8C98B),
    // rgb(201 194 154 / 0.5)
    line: Color(0x80C9C29A),
    // rgb(166 166 166 / 0.5)
    lineStrong: Color(0x80A6A6A6),
  );

  static SsColors of(BuildContext context) =>
      Theme.of(context).extension<SsColors>() ?? light;

  @override
  SsColors copyWith({
    Color? canvas,
    Color? accent,
    Color? neutral,
    Color? primary,
    Color? primaryDark,
    Color? primaryLight,
    Color? selected,
    Color? ink,
    Color? danger,
    Color? success,
    Color? warning,
    Color? line,
    Color? lineStrong,
  }) => SsColors(
    canvas: canvas ?? this.canvas,
    accent: accent ?? this.accent,
    neutral: neutral ?? this.neutral,
    primary: primary ?? this.primary,
    primaryDark: primaryDark ?? this.primaryDark,
    primaryLight: primaryLight ?? this.primaryLight,
    selected: selected ?? this.selected,
    ink: ink ?? this.ink,
    danger: danger ?? this.danger,
    success: success ?? this.success,
    warning: warning ?? this.warning,
    line: line ?? this.line,
    lineStrong: lineStrong ?? this.lineStrong,
  );

  @override
  SsColors lerp(ThemeExtension<SsColors>? other, double t) {
    if (other is! SsColors) return this;
    return SsColors(
      canvas: Color.lerp(canvas, other.canvas, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      neutral: Color.lerp(neutral, other.neutral, t)!,
      primary: Color.lerp(primary, other.primary, t)!,
      primaryDark: Color.lerp(primaryDark, other.primaryDark, t)!,
      primaryLight: Color.lerp(primaryLight, other.primaryLight, t)!,
      selected: Color.lerp(selected, other.selected, t)!,
      ink: Color.lerp(ink, other.ink, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      success: Color.lerp(success, other.success, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      line: Color.lerp(line, other.line, t)!,
      lineStrong: Color.lerp(lineStrong, other.lineStrong, t)!,
    );
  }
}

/// Fixed brand gradient for the record diamond's green state: a 3D sheen
/// (light top to dark bottom) that stays the same in both themes, like the
/// button's red "recording" gradient right beside it.
const kRecordGreenGradient = [
  Color(0xFF5A8A56),
  Color(0xFF4B6E48),
  Color(0xFF34502F),
];

const _kFont = 'YekanBakh';

TextStyle _text(
  double size,
  FontWeight weight,
  Color color, {
  double? height,
}) => TextStyle(
  fontFamily: _kFont,
  fontSize: size,
  fontWeight: weight,
  color: color,
  height: height,
);

ThemeData buildAppTheme([Brightness brightness = Brightness.light]) {
  final dark = brightness == Brightness.dark;
  final c = dark ? SsColors.dark : SsColors.light;

  final scheme = ColorScheme(
    brightness: brightness,
    primary: c.primary,
    onPrimary: dark ? const Color(0xFF12210F) : c.canvas,
    primaryContainer: c.selected,
    onPrimaryContainer: c.primaryDark,
    secondary: c.accent,
    onSecondary: dark ? c.canvas : c.primaryDark,
    secondaryContainer: c.selected,
    onSecondaryContainer: c.primaryDark,
    tertiary: c.neutral,
    onTertiary: c.canvas,
    error: c.danger,
    onError: dark ? const Color(0xFF2A0A10) : Colors.white,
    errorContainer: dark ? const Color(0xFF3A1620) : const Color(0xFFF3DDE0),
    onErrorContainer: dark ? const Color(0xFFFFB3C1) : c.danger,
    surface: c.canvas,
    onSurface: c.ink,
    onSurfaceVariant: c.neutral,
    outline: c.lineStrong,
    outlineVariant: c.line,
    surfaceTint: Colors.transparent,
    surfaceContainerLowest: c.canvas,
    surfaceContainerLow: c.canvas,
    surfaceContainer: c.canvas,
    surfaceContainerHigh: c.selected,
    surfaceContainerHighest: c.selected,
    inverseSurface: c.primaryDark,
    onInverseSurface: c.canvas,
  );

  final border = BorderSide(color: c.line);
  final strongBorder = BorderSide(color: c.lineStrong);
  const square = RoundedRectangleBorder();
  final squareLine = RoundedRectangleBorder(side: border);

  OutlineInputBorder inputBorder(Color col, [double w = 1]) =>
      OutlineInputBorder(
        borderRadius: BorderRadius.zero,
        borderSide: BorderSide(color: col, width: w),
      );

  final textTheme = TextTheme(
    displayLarge: _text(44, FontWeight.w500, c.ink),
    displayMedium: _text(38, FontWeight.w500, c.ink),
    displaySmall: _text(32, FontWeight.w500, c.ink),
    headlineLarge: _text(28, FontWeight.w500, c.primary),
    headlineMedium: _text(24, FontWeight.w500, c.primary),
    headlineSmall: _text(20, FontWeight.w500, c.primary),
    titleLarge: _text(18, FontWeight.w500, c.primary),
    titleMedium: _text(15, FontWeight.w500, c.primary),
    titleSmall: _text(14, FontWeight.w500, c.primary),
    bodyLarge: _text(15, FontWeight.w400, c.ink, height: 1.7),
    bodyMedium: _text(14, FontWeight.w400, c.ink, height: 1.7),
    bodySmall: _text(12, FontWeight.w400, c.neutral, height: 1.7),
    labelLarge: _text(14, FontWeight.w500, c.ink),
    labelMedium: _text(12, FontWeight.w500, c.ink),
    labelSmall: _text(11, FontWeight.w400, c.neutral),
  );

  return ThemeData(
    brightness: brightness,
    colorScheme: scheme,
    extensions: [c],
    useMaterial3: true,
    fontFamily: _kFont,
    textTheme: textTheme,
    scaffoldBackgroundColor: c.canvas,
    canvasColor: c.canvas,
    splashFactory: NoSplash.splashFactory,
    // Pin one back-arrow glyph everywhere instead of Flutter's per-platform
    // default, which swaps in a bulkier iOS/macOS chevron.
    actionIconTheme: ActionIconThemeData(
      // Icons.arrow_back already mirrors for RTL (IconData.matchTextDirection).
      backButtonIconBuilder: (context) => const Icon(Icons.arrow_back),
    ),
    dividerTheme: DividerThemeData(color: c.line, thickness: 1, space: 1),
    appBarTheme: AppBarTheme(
      centerTitle: false,
      // leadingWidth is set per bar by SsAppBar itself (to fit its edge
      // gap), not here — every AppBar in the app goes through it.
      titleSpacing: 0,
      elevation: 0,
      scrolledUnderElevation: 0,
      backgroundColor: c.canvas,
      foregroundColor: c.ink,
      surfaceTintColor: Colors.transparent,
      systemOverlayStyle: dark
          ? const SystemUiOverlayStyle(
              statusBarColor: Colors.transparent,
              statusBarIconBrightness: Brightness.light,
              statusBarBrightness: Brightness.dark,
            )
          : const SystemUiOverlayStyle(
              statusBarColor: Colors.transparent,
              statusBarIconBrightness: Brightness.dark,
              statusBarBrightness: Brightness.light,
            ),
      iconTheme: IconThemeData(color: c.ink),
      actionsIconTheme: IconThemeData(color: c.ink),
      titleTextStyle: _text(17, FontWeight.w500, c.ink),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: c.canvas,
      surfaceTintColor: Colors.transparent,
      margin: EdgeInsets.zero,
      shape: squareLine,
    ),
    listTileTheme: ListTileThemeData(
      shape: square,
      iconColor: c.primary,
      textColor: c.ink,
      titleTextStyle: _text(14, FontWeight.w500, c.ink),
      subtitleTextStyle: _text(12, FontWeight.w400, c.neutral),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: c.primary,
        foregroundColor: scheme.onPrimary,
        disabledBackgroundColor: c.line,
        disabledForegroundColor: c.neutral,
        shape: square,
        minimumSize: const Size(0, 44),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        textStyle: _text(14, FontWeight.w500, scheme.onPrimary),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: c.primary,
        foregroundColor: scheme.onPrimary,
        elevation: 0,
        shape: square,
        minimumSize: const Size(0, 44),
        textStyle: _text(14, FontWeight.w500, scheme.onPrimary),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: c.primary,
        side: strongBorder,
        shape: square,
        minimumSize: const Size(0, 44),
        textStyle: _text(14, FontWeight.w500, c.primary),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: c.primary,
        shape: square,
        textStyle: _text(14, FontWeight.w500, c.primary),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(shape: square),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: c.primary,
      foregroundColor: scheme.onPrimary,
      elevation: 0,
      focusElevation: 0,
      hoverElevation: 0,
      highlightElevation: 0,
      shape: square,
      extendedTextStyle: _text(14, FontWeight.w500, scheme.onPrimary),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.canvas,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: inputBorder(c.line),
      enabledBorder: inputBorder(c.line),
      disabledBorder: inputBorder(c.line),
      focusedBorder: inputBorder(c.primary),
      errorBorder: inputBorder(c.danger),
      focusedErrorBorder: inputBorder(c.danger),
      labelStyle: _text(13, FontWeight.w400, c.neutral),
      hintStyle: _text(13, FontWeight.w400, c.neutral),
    ),
    dropdownMenuTheme: DropdownMenuThemeData(
      menuStyle: MenuStyle(
        shape: WidgetStatePropertyAll(squareLine),
        backgroundColor: WidgetStatePropertyAll(c.canvas),
        elevation: const WidgetStatePropertyAll(0),
      ),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: c.canvas,
      elevation: 0,
      shape: squareLine,
      surfaceTintColor: Colors.transparent,
      menuPadding: const EdgeInsets.symmetric(vertical: 2),
      textStyle: _text(13, FontWeight.w400, c.ink),
    ),
    menuTheme: MenuThemeData(
      style: MenuStyle(
        shape: WidgetStatePropertyAll(squareLine),
        backgroundColor: WidgetStatePropertyAll(c.canvas),
        elevation: const WidgetStatePropertyAll(0),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: c.canvas,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(side: strongBorder),
      titleTextStyle: _text(17, FontWeight.w500, c.primary),
      contentTextStyle: _text(14, FontWeight.w400, c.ink, height: 1.7),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: c.canvas,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(side: strongBorder),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: c.primaryDark,
      contentTextStyle: _text(13, FontWeight.w400, c.canvas),
      shape: square,
      behavior: SnackBarBehavior.floating,
      elevation: 0,
    ),
    chipTheme: ChipThemeData(
      backgroundColor: c.canvas,
      selectedColor: c.selected,
      disabledColor: c.canvas,
      side: border,
      shape: square,
      showCheckmark: true,
      checkmarkColor: c.primary,
      labelStyle: _text(13, FontWeight.w400, c.ink),
      secondaryLabelStyle: _text(13, FontWeight.w500, c.primaryDark),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: 64,
      backgroundColor: c.canvas,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      indicatorColor: c.selected,
      indicatorShape: square,
      iconTheme: WidgetStateProperty.resolveWith(
        (s) => IconThemeData(
          color: s.contains(WidgetState.selected) ? c.primary : c.neutral,
        ),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (s) => _text(
          12,
          s.contains(WidgetState.selected) ? FontWeight.w500 : FontWeight.w400,
          s.contains(WidgetState.selected) ? c.primary : c.neutral,
        ),
      ),
    ),
    tabBarTheme: TabBarThemeData(
      labelColor: c.primary,
      unselectedLabelColor: c.neutral,
      indicatorColor: c.primary,
      dividerColor: c.line,
      labelStyle: _text(14, FontWeight.w500, c.primary),
      unselectedLabelStyle: _text(14, FontWeight.w400, c.neutral),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        shape: square,
        side: border,
        backgroundColor: c.canvas,
        foregroundColor: c.ink,
        selectedBackgroundColor: c.selected,
        selectedForegroundColor: c.primaryDark,
      ),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? c.canvas : c.neutral,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? c.primary : c.line,
      ),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
    ),
    checkboxTheme: CheckboxThemeData(
      shape: square,
      side: strongBorder,
      fillColor: WidgetStateProperty.resolveWith(
        (s) =>
            s.contains(WidgetState.selected) ? c.primary : Colors.transparent,
      ),
    ),
    radioTheme: RadioThemeData(fillColor: WidgetStateProperty.all(c.primary)),
    sliderTheme: SliderThemeData(
      activeTrackColor: c.primary,
      inactiveTrackColor: c.line,
      thumbColor: c.primary,
      overlayColor: Colors.transparent,
      trackShape: const RectangularSliderTrackShape(),
      thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 6),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: c.primary,
      linearTrackColor: c.line,
      circularTrackColor: Colors.transparent,
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(color: c.primaryDark),
      textStyle: _text(12, FontWeight.w400, c.canvas),
    ),
    expansionTileTheme: const ExpansionTileThemeData(
      shape: Border(),
      collapsedShape: Border(),
    ),
  );
}
