/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#f8fafc",        // Crisp Cool Slate-50 Canvas
        panel: "#ffffff",      // Pure Crisp White Panel
        raised: "#f1f5f9",     // Slate-100 Level 2
        line: "#e2e8f0",       // Clean Hairline Slate Border
        mist: "#64748b",       // Slate-500 Muted Text
        paper: "#0f172a",      // High-Contrast Slate-900 Text
        neon: "#2563eb",       // Modern Tech Blue Accent
        gold: "#2563eb",       // Tech Blue
        goldBright: "#3b82f6", // Vivid Blue Accent
        amber: "#d97706",      // Status Amber
        danger: "#ef4444",     // Status Red
      },
      fontFamily: {
        sans: ["Vazirmatn", "Tahoma", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 35px -8px rgba(15, 23, 42, 0.08)",
      },
    },
  },
  plugins: [],
};
