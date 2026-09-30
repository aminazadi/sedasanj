/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}", "./node_modules/@cbi/web-shared/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Vazirmatn", "IRANSans", "system-ui", "sans-serif"] },
      colors: {
        brand: { 50: "#eef6ff", 500: "#2f6feb", 600: "#255bc4", 700: "#1d4699" },
      },
    },
  },
  plugins: [],
};
