/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Driven by CSS variables set from per-company branding
        brand: "var(--brand-primary)",
        brand2: "var(--brand-secondary)",
        accent: "var(--brand-accent)",
      },
    },
  },
  plugins: [],
};
