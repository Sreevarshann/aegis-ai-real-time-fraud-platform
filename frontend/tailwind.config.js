/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#060a14", 900: "#0a1020", 850: "#0d1426", 800: "#111a2e", 700: "#1a2540", 600: "#25314f" },
        line: "#1e2a44",
        mist: { 100: "#e6ebf5", 300: "#aab6cf", 400: "#8593b0", 500: "#62708f" },
        signal: { DEFAULT: "#4c8dff", soft: "#2b5cc4" },
        teal: { DEFAULT: "#2dd4bf", soft: "#14806f" },
        risk: { low: "#34d399", medium: "#fbbf24", high: "#fb923c", critical: "#f43f5e" },
      },
      fontFamily: {
        sans: ['"Inter Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: { panel: "0 0 0 1px rgba(76,141,255,0.06), 0 8px 24px -12px rgba(0,0,0,0.6)" },
      keyframes: {
        fadein: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
        flash: { from: { backgroundColor: "rgba(76,141,255,0.18)" }, to: { backgroundColor: "transparent" } },
      },
      animation: { fadein: "fadein .35s ease-out both", flash: "flash 1.6s ease-out" },
    },
  },
  plugins: [],
};
