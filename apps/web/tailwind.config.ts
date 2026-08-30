import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0f1c",
          900: "#0d1424",
          850: "#111a2e",
          800: "#16203a",
          700: "#1e2b4d",
        },
        accent: {
          green: "#22c55e",
          blue: "#3b82f6",
          amber: "#f59e0b",
          red: "#ef4444",
          violet: "#8b5cf6",
        },
      },
      fontFamily: {
        sans: ["Inter", "Padauk", "Noto Sans Myanmar", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
