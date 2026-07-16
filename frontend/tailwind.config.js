/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        purple: {
          600: '#7C3AED',
          700: '#6D28D9',
        },
      },
    },
  },
  plugins: [],
};
