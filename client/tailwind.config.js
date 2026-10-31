/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#070b10",
        panel: "#0d141d",
        raised: "#121c27",
        line: "#223140",
        mist: "#8ba3b8",
        paper: "#e8f2f8",
        neon: "#5eead4",
        amber: "#fbbf24",
        danger: "#fb7185",
      },
      fontFamily: {
        sans: ["Vazirmatn", "Tahoma", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 60px -18px rgba(94, 234, 212, 0.55)",
      },
    },
  },
  plugins: [],
};
