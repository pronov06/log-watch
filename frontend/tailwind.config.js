/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        cream: '#ECECE3',
        paper: '#F5F5EF',
        line: '#D3D3C7',
        ink: '#1F1F1F',
        muted: '#6B6B66',
        forest: { DEFAULT: '#2C3E2E', dark: '#233325', soft: '#DDE3D6' },
        sev: {
          critical: '#9B2C1F',
          high: '#B4501F',
          medium: '#9A6B12',
          low: '#6F6A1C',
          ok: '#2C3E2E',
        },
      },
      fontFamily: {
        serif: ['"Playfair Display"', 'Georgia', 'serif'],
        sans: ['Inter', '"Helvetica Neue"', 'Arial', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      borderRadius: { DEFAULT: '3px', md: '4px' },
    },
  },
  plugins: [],
}
