import type { Config } from "tailwindcss";
const config: Config = {
  content: ["./app/**/*.{ts,tsx}","./components/**/*.{ts,tsx}","./providers/**/*.{ts,tsx}"],
  theme: { extend: { colors: { background:"var(--background)", foreground:"var(--foreground)", card:"var(--card)", border:"var(--border)", primary:"var(--primary)", muted:"var(--muted)" }, borderRadius: { xl:"var(--radius-xl)", lg:"var(--radius-lg)" } } },
  plugins: [],
};
export default config;
