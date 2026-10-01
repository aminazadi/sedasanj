import { tailwindColors } from "../shared/theme.js";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}", "./node_modules/@cbi/web-shared/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Vazirmatn", "IRANSans", "system-ui", "sans-serif"] },
      colors: tailwindColors,
    },
  },
  plugins: [],
};
