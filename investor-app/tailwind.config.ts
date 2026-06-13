import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        nav:        "#1C1C28",
        background: "#F8FAFB",
        surface:    "#FFFFFF",
        border:     "#E8EAEC",
        accent: {
          DEFAULT: "#0891B2",
          light:   "#ECFEFF",
          dark:    "#0E7490",
        },
        positive: "#1F9B55",
        negative: "#D84040",
        text: {
          primary: "#1A1A1A",
          muted:   "#888888",
        },
      },
      borderRadius: {
        card:  "12px",
        hero:  "14px",
        btn:   "8px",
        pill:  "20px",
        input: "8px",
      },
      fontSize: {
        "hero-val":   ["28px", { fontWeight: "500", letterSpacing: "-0.5px" }],
        "page-title": ["20px", { fontWeight: "500" }],
        "section":    ["13px", { fontWeight: "500" }],
        "body":       ["13px", { fontWeight: "400" }],
        "label":      ["11px", { fontWeight: "400" }],
        "meta":       ["10px", { fontWeight: "400" }],
      },
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
      boxShadow:  { card: "0 1px 3px rgba(0,0,0,0.06)" },
    },
  },
  plugins: [],
};

export default config;
