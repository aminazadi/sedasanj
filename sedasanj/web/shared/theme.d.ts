export type ColorScale = Record<50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 | 950, string>;

export const palette: {
  canvas: string;
  accent: string;
  neutral: string;
  primary: string;
  primaryDark: string;
  primaryLight: string;
  selected: string;
  ink: string;
  inkSoft: string;
  danger: string;
  success: string;
  warning: string;
};
export const brand: ColorScale;
export const neutral: ColorScale;
export const accent: ColorScale;

export type ChartColors = {
  primary: string;
  secondary: string;
  success: string;
  danger: string;
  warning: string;
  violet: string;
  cyan: string;
  neutral: string;
  light: string;
  dark: string;
  categorical: string[];
};
export const chartLight: ChartColors;
export const chartDark: ChartColors;
/** @deprecated use `chartLight`/`chartDark`. */
export const chart: ChartColors;

export const tailwindColors: Record<string, ColorScale | string>;
