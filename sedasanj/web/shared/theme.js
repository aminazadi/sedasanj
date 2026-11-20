// Brand color tokens shared by the admin and client panels, and by the
// Jalase-Negar app (jalase-negar/lib/app/theme.dart, same hex values, kept
// in sync by hand). Each token is a CSS custom property pair declared in
// styles/theme-vars.css: a plain hex value for direct `var(--x)` use, and an
// "-rgb" sibling (space-separated channels) that lets Tailwind's
// `rgb(var(--x-rgb) / <alpha-value>)` pattern respond to opacity modifiers
// (`bg-canvas/50`) the same way a literal hex color would. Redeclaring the
// vars under `:root[data-theme="dark"]` (see theme-vars.css) is what makes
// every one of these classes repaint for dark mode with no per-component
// change.
export const palette = {
  canvas: "rgb(var(--color-canvas-rgb) / <alpha-value>)",
  accent: "rgb(var(--color-accent-rgb) / <alpha-value>)",
  neutral: "rgb(var(--color-neutral-rgb) / <alpha-value>)",
  primary: "rgb(var(--color-primary-rgb) / <alpha-value>)",
  primaryDark: "rgb(var(--color-primary-dark-rgb) / <alpha-value>)",
  primaryLight: "rgb(var(--color-primary-light-rgb) / <alpha-value>)",
  selected: "rgb(var(--color-selected-rgb) / <alpha-value>)",
  ink: "rgb(var(--ink-rgb) / <alpha-value>)",
  inkSoft: "rgb(var(--ink-soft-rgb) / <alpha-value>)",
  danger: "rgb(var(--color-danger-rgb) / <alpha-value>)",
  success: "rgb(var(--color-success-rgb) / <alpha-value>)",
  warning: "rgb(var(--color-warning-rgb) / <alpha-value>)",
};

export const brand = {
  50: palette.canvas,
  100: palette.canvas,
  200: palette.accent,
  300: palette.accent,
  400: palette.neutral,
  500: palette.primary,
  600: palette.primary,
  700: palette.primary,
  800: palette.primary,
  900: palette.primary,
  950: palette.primary,
};

export const neutral = {
  50: palette.canvas,
  100: palette.canvas,
  200: palette.accent,
  300: palette.accent,
  400: palette.neutral,
  500: palette.neutral,
  600: palette.neutral,
  700: palette.primary,
  800: palette.primary,
  900: palette.primary,
  950: palette.primary,
};

export const accent = {
  50: palette.canvas,
  100: palette.canvas,
  200: palette.accent,
  300: palette.accent,
  400: palette.accent,
  500: palette.accent,
  600: palette.neutral,
  700: palette.neutral,
  800: palette.primary,
  900: palette.primary,
  950: palette.primary,
};

/** Fixed (not theme-reactive) chart colors — Recharts/SVG take literal
 * values, so `useChartColors()` below picks one of these two sets by hand
 * instead of relying on CSS variables. */
export const chartLight = {
  primary: "#4b6e48",
  secondary: "#b2ac88",
  success: "#5f805b",
  danger: "#7a625c",
  warning: "#9c9678",
  violet: "#6c8068",
  cyan: "#789074",
  neutral: "#898989",
  light: "#d8d4c2",
  dark: "#4b6e48",
  categorical: ["#4B6E48", "#B2AC88", "#898989", "#657B61", "#C7C1A5", "#73816F", "#9C9678"],
};

export const chartDark = {
  primary: "#5fa05a",
  secondary: "#c9c29a",
  success: "#7fbf78",
  danger: "#c98f8a",
  warning: "#d8c98b",
  violet: "#93a98f",
  cyan: "#9ab296",
  neutral: "#a6a6a6",
  light: "#3c3a34",
  dark: "#5fa05a",
  categorical: ["#5FA05A", "#C9C29A", "#A6A6A6", "#7FA37A", "#D8D4C2", "#8CA088", "#D8C98B"],
};

/** @deprecated use `chartLight`/`chartDark` (or `useChartColors()` in a
 * component) so chart colors follow the chosen theme. Kept pointing at the
 * light set for any caller not yet migrated. */
export const chart = chartLight;

export const tailwindColors = {
  brand,
  slate: neutral,
  gray: neutral,
  zinc: neutral,
  neutral,
  stone: neutral,
  green: brand,
  emerald: brand,
  teal: brand,
  blue: brand,
  sky: brand,
  cyan: brand,
  indigo: brand,
  violet: brand,
  purple: brand,
  lime: brand,
  amber: accent,
  yellow: accent,
  orange: accent,
  red: neutral,
  rose: neutral,
  pink: neutral,
  canvas: palette.canvas,
  ink: palette.ink,
  "ink-soft": palette.inkSoft,
  "primary-dark": palette.primaryDark,
  "primary-light": palette.primaryLight,
  selected: palette.selected,
};
