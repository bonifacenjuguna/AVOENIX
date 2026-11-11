import type { Config } from "tailwindcss";
// Colours are CSS variables (app/globals.css); Tailwind is used for layout/spacing only. Dark mode is driven by data-theme, not the OS media query.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: { extend: { fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"] } } },
  plugins: [],
};
export default config;
