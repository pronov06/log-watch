import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend the dev server proxies to; override with BACKEND_URL=http://127.0.0.1:8010 npm run dev
const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
      },
      '/ws': {
        target: backend.replace(/^http/, 'ws'),
        ws: true,
      },
    },
  },
});
