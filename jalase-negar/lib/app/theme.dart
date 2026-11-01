import 'package:flutter/material.dart';

/// Brand tokens shared with the SedaSanj web panel (shared/theme.js, index.css).
abstract final class SsColors {
  static const canvas = Color(0xFFF2F0EF);
  static const accent = Color(0xFFB2AC88);
  static const neutral = Color(0xFF898989);
  static const primary = Color(0xFF4B6E48);
  static const primaryDark = Color(0xFF3E5C3B);
  static const primaryLight = Color(0xFF4F7A4C);
  static const selected = Color(0xFFE7ECDD);
  static const ink = Color(0xFF334155);
  static const danger = Color(0xFFBE123C);
  static const success = Color(0xFF5F805B);
  static const warning = Color(0xFF9C9678);

  /// rgb(178 172 136 / 0.5)
  static const line = Color(0x80B2AC88);

  /// rgb(137 137 137 / 0.5)
  static const lineStrong = Color(0x80898989);
}

const _kFont = 'Vazirmatn';

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

ThemeData buildAppTheme() {
  const scheme = ColorScheme(
    brightness: Brightness.light,
    primary: SsColors.primary,
    onPrimary: SsColors.canvas,
    primaryContainer: SsColors.selected,
    onPrimaryContainer: SsColors.primaryDark,
    secondary: SsColors.accent,
    onSecondary: SsColors.primaryDark,
    secondaryContainer: SsColors.selected,
    onSecondaryContainer: SsColors.primaryDark,
    tertiary: SsColors.neutral,
    onTertiary: SsColors.canvas,
    error: SsColors.danger,
    onError: Colors.white,
    errorContainer: Color(0xFFF3DDE0),
    onErrorContainer: SsColors.danger,
    surface: SsColors.canvas,
    onSurface: SsColors.ink,
    onSurfaceVariant: SsColors.neutral,
    outline: SsColors.lineStrong,
    outlineVariant: SsColors.line,
    surfaceTint: Colors.transparent,
    surfaceContainerLowest: SsColors.canvas,
    surfaceContainerLow: SsColors.canvas,
    surfaceContainer: SsColors.canvas,
    surfaceContainerHigh: SsColors.selected,
    surfaceContainerHighest: SsColors.selected,
    inverseSurface: SsColors.primaryDark,
    onInverseSurface: SsColors.canvas,
  );

  const border = BorderSide(color: SsColors.line);
  const strongBorder = BorderSide(color: SsColors.lineStrong);
  const square = RoundedRectangleBorder();
  const squareLine = RoundedRectangleBorder(side: border);

  OutlineInputBorder inputBorder(Color c, [double w = 1]) => OutlineInputBorder(
    borderRadius: BorderRadius.zero,
    borderSide: BorderSide(color: c, width: w),
  );

  final textTheme = TextTheme(
    displayLarge: _text(44, FontWeight.w500, SsColors.ink),
    displayMedium: _text(38, FontWeight.w500, SsColors.ink),
    displaySmall: _text(32, FontWeight.w500, SsColors.ink),
    headlineLarge: _text(28, FontWeight.w500, SsColors.primary),
    headlineMedium: _text(24, FontWeight.w500, SsColors.primary),
    headlineSmall: _text(20, FontWeight.w500, SsColors.primary),
    titleLarge: _text(18, FontWeight.w500, SsColors.primary),
    titleMedium: _text(15, FontWeight.w500, SsColors.primary),
    titleSmall: _text(14, FontWeight.w500, SsColors.primary),
    bodyLarge: _text(15, FontWeight.w400, SsColors.ink, height: 1.7),
    bodyMedium: _text(14, FontWeight.w400, SsColors.ink, height: 1.7),
    bodySmall: _text(12, FontWeight.w400, SsColors.neutral, height: 1.7),
    labelLarge: _text(14, FontWeight.w500, SsColors.ink),
    labelMedium: _text(12, FontWeight.w500, SsColors.ink),
    labelSmall: _text(11, FontWeight.w400, SsColors.neutral),
  );

  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    fontFamily: _kFont,
    textTheme: textTheme,
    scaffoldBackgroundColor: SsColors.canvas,
    canvasColor: SsColors.canvas,
    splashFactory: NoSplash.splashFactory,
    dividerTheme: const DividerThemeData(
      color: SsColors.line,
      thickness: 1,
      space: 1,
    ),
    appBarTheme: AppBarTheme(
      centerTitle: false,
      elevation: 0,
      scrolledUnderElevation: 0,
      backgroundColor: SsColors.primary,
      foregroundColor: SsColors.canvas,
      surfaceTintColor: Colors.transparent,
      iconTheme: const IconThemeData(color: SsColors.canvas),
      actionsIconTheme: const IconThemeData(color: SsColors.canvas),
      titleTextStyle: _text(17, FontWeight.w500, SsColors.canvas),
    ),
    cardTheme: const CardThemeData(
      elevation: 0,
      color: SsColors.canvas,
      surfaceTintColor: Colors.transparent,
      margin: EdgeInsets.zero,
      shape: squareLine,
    ),
    listTileTheme: ListTileThemeData(
      shape: square,
      iconColor: SsColors.primary,
      textColor: SsColors.ink,
      titleTextStyle: _text(14, FontWeight.w500, SsColors.ink),
      subtitleTextStyle: _text(12, FontWeight.w400, SsColors.neutral),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: SsColors.primary,
        foregroundColor: SsColors.canvas,
        disabledBackgroundColor: SsColors.line,
        disabledForegroundColor: SsColors.neutral,
        shape: square,
        minimumSize: const Size(0, 44),
        padding: const EdgeInsets.symmetric(horizontal: 20),
        textStyle: _text(14, FontWeight.w500, SsColors.canvas),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: SsColors.primary,
        foregroundColor: SsColors.canvas,
        elevation: 0,
        shape: square,
        minimumSize: const Size(0, 44),
        textStyle: _text(14, FontWeight.w500, SsColors.canvas),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: SsColors.primary,
        side: strongBorder,
        shape: square,
        minimumSize: const Size(0, 44),
        textStyle: _text(14, FontWeight.w500, SsColors.primary),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: SsColors.primary,
        shape: square,
        textStyle: _text(14, FontWeight.w500, SsColors.primary),
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(shape: square),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: SsColors.primary,
      foregroundColor: SsColors.canvas,
      elevation: 0,
      focusElevation: 0,
      hoverElevation: 0,
      highlightElevation: 0,
      shape: square,
      extendedTextStyle: _text(14, FontWeight.w500, SsColors.canvas),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: SsColors.canvas,
      isDense: true,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: inputBorder(SsColors.line),
      enabledBorder: inputBorder(SsColors.line),
      disabledBorder: inputBorder(SsColors.line),
      focusedBorder: inputBorder(SsColors.primary),
      errorBorder: inputBorder(SsColors.danger),
      focusedErrorBorder: inputBorder(SsColors.danger),
      labelStyle: _text(13, FontWeight.w400, SsColors.neutral),
      hintStyle: _text(13, FontWeight.w400, SsColors.neutral),
    ),
    dropdownMenuTheme: DropdownMenuThemeData(
      menuStyle: const MenuStyle(
        shape: WidgetStatePropertyAll(squareLine),
        backgroundColor: WidgetStatePropertyAll(SsColors.canvas),
        elevation: WidgetStatePropertyAll(0),
      ),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: SsColors.canvas,
      elevation: 0,
      shape: squareLine,
      surfaceTintColor: Colors.transparent,
      textStyle: _text(13, FontWeight.w400, SsColors.ink),
    ),
    menuTheme: const MenuThemeData(
      style: MenuStyle(
        shape: WidgetStatePropertyAll(squareLine),
        backgroundColor: WidgetStatePropertyAll(SsColors.canvas),
        elevation: WidgetStatePropertyAll(0),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: SsColors.canvas,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: const RoundedRectangleBorder(side: strongBorder),
      titleTextStyle: _text(17, FontWeight.w500, SsColors.primary),
      contentTextStyle: _text(14, FontWeight.w400, SsColors.ink, height: 1.7),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      backgroundColor: SsColors.canvas,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(side: strongBorder),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: SsColors.primaryDark,
      contentTextStyle: _text(13, FontWeight.w400, SsColors.canvas),
      shape: square,
      behavior: SnackBarBehavior.floating,
      elevation: 0,
    ),
    chipTheme: ChipThemeData(
      backgroundColor: SsColors.canvas,
      selectedColor: SsColors.selected,
      disabledColor: SsColors.canvas,
      side: border,
      shape: square,
      showCheckmark: true,
      checkmarkColor: SsColors.primary,
      labelStyle: _text(13, FontWeight.w400, SsColors.ink),
      secondaryLabelStyle: _text(13, FontWeight.w500, SsColors.primaryDark),
    ),
    navigationBarTheme: NavigationBarThemeData(
      height: 64,
      backgroundColor: SsColors.canvas,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      indicatorColor: SsColors.selected,
      indicatorShape: square,
      iconTheme: WidgetStateProperty.resolveWith(
        (s) => IconThemeData(
          color: s.contains(WidgetState.selected)
              ? SsColors.primary
              : SsColors.neutral,
        ),
      ),
      labelTextStyle: WidgetStateProperty.resolveWith(
        (s) => _text(
          12,
          s.contains(WidgetState.selected) ? FontWeight.w500 : FontWeight.w400,
          s.contains(WidgetState.selected)
              ? SsColors.primary
              : SsColors.neutral,
        ),
      ),
    ),
    tabBarTheme: TabBarThemeData(
      labelColor: SsColors.primary,
      unselectedLabelColor: SsColors.neutral,
      indicatorColor: SsColors.primary,
      dividerColor: SsColors.line,
      labelStyle: _text(14, FontWeight.w500, SsColors.primary),
      unselectedLabelStyle: _text(14, FontWeight.w400, SsColors.neutral),
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        shape: square,
        side: border,
        backgroundColor: SsColors.canvas,
        foregroundColor: SsColors.ink,
        selectedBackgroundColor: SsColors.selected,
        selectedForegroundColor: SsColors.primaryDark,
      ),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected)
            ? SsColors.canvas
            : SsColors.neutral,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (s) =>
            s.contains(WidgetState.selected) ? SsColors.primary : SsColors.line,
      ),
      trackOutlineColor: const WidgetStatePropertyAll(Colors.transparent),
    ),
    checkboxTheme: CheckboxThemeData(
      shape: square,
      side: strongBorder,
      fillColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected)
            ? SsColors.primary
            : Colors.transparent,
      ),
    ),
    radioTheme: RadioThemeData(
      fillColor: WidgetStateProperty.all(SsColors.primary),
    ),
    sliderTheme: const SliderThemeData(
      activeTrackColor: SsColors.primary,
      inactiveTrackColor: SsColors.line,
      thumbColor: SsColors.primary,
      overlayColor: Colors.transparent,
      trackShape: RectangularSliderTrackShape(),
      thumbShape: RoundSliderThumbShape(enabledThumbRadius: 6),
    ),
    progressIndicatorTheme: const ProgressIndicatorThemeData(
      color: SsColors.primary,
      linearTrackColor: SsColors.line,
      circularTrackColor: Colors.transparent,
    ),
    tooltipTheme: TooltipThemeData(
      decoration: const BoxDecoration(color: SsColors.primaryDark),
      textStyle: _text(12, FontWeight.w400, SsColors.canvas),
    ),
    expansionTileTheme: const ExpansionTileThemeData(
      shape: Border(),
      collapsedShape: Border(),
    ),
  );
}
