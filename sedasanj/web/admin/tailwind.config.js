/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}", "./node_modules/@cbi/web-shared/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Vazirmatn", "IRANSans", "system-ui", "sans-serif"] },
      colors: {
        brand: { 50: "#f3f0ff", 500: "#6d4aff", 600: "#5a37e0", 700: "#4728b4" },
      },
    },
  },
  plugins: [],
};
