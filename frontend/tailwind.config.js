/** @type {import('tailwindcss').Config} */
// AEGIS design tokens: white surfaces, professional blue accent, slate text.
// Chart series colours (see src/components/charts.tsx) are validated for CVD separation on #ffffff.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f4f6fb", // app background
        surface: "#ffffff", // cards, sidebar, top bar
        sunken: "#f8fafc", // inputs, nested blocks
        hover: "#f1f5fb", // row / item hover
        track: "#e8edf5", // progress tracks, skeletons
        line: { DEFAULT: "#e6eaf2", strong: "#d5dbe6" },
        fg: { DEFAULT: "#0f172a", 2: "#475569", 3: "#64748b", 4: "#94a3b8" },
        signal: { DEFAULT: "#2563eb", hover: "#1d4ed8", soft: "#eff4ff", ring: "#bfd3fe" },
        teal: { DEFAULT: "#0d9488", soft: "#e6f6f4" },
        risk: { low: "#16a34a", medium: "#d97706", high: "#ea580c", critical: "#dc2626" },
      },
      fontFamily: {
        sans: ['"Inter Variable"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,0.04), 0 4px 16px -4px rgba(15,23,42,0.06)",
        lift: "0 2px 4px rgba(15,23,42,0.04), 0 12px 32px -8px rgba(15,23,42,0.12)",
        brand: "0 8px 20px -6px rgba(37,99,235,0.45)",
      },
      borderRadius: { xl: "14px", "2xl": "18px" },
      keyframes: {
        fadein: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
        flash: { from: { backgroundColor: "rgba(37,99,235,0.10)" }, to: { backgroundColor: "transparent" } },
      },
      animation: { fadein: "fadein .3s ease-out both", flash: "flash 1.6s ease-out" },
    },
  },
  plugins: [],
};
