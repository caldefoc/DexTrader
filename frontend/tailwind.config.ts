import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        background: "#020817",
        foreground: "#f9fafb",
        primary: {
          DEFAULT: "#22c55e",
          foreground: "#020617"
        },
        secondary: {
          DEFAULT: "#0f172a",
          foreground: "#e5e7eb"
        }
      }
    }
  },
  plugins: []
};

export default config;

