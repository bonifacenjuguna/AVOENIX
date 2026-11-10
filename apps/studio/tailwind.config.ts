import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: { extend: { fontFamily: { sans: ["ui-sans-serif", "system-ui", "sans-serif"] } } },
  plugins: [],
};
export default config;
