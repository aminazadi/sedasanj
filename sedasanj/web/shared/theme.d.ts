export type ColorScale = Record<50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 | 950, string>;

export const palette: {
  canvas: string;
  accent: string;
  neutral: string;
  primary: string;
};
export const brand: ColorScale;
export const neutral: ColorScale;
export const accent: ColorScale;
export const chart: {
  primary: string;
  secondary: string;
  neutral: string;
  light: string;
  dark: string;
};
export const tailwindColors: Record<string, ColorScale>;
