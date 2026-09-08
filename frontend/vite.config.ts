import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin /api in development, exactly as CloudFront serves it in
    // staging: the app calls relative /api/v1/... and never needs CORS.
    proxy: {
      '/api': {
        // 127.0.0.1, not localhost: Node resolves localhost to ::1 first and
        // uvicorn listens on IPv4, so "localhost" would be refused.
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})