import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            // Must exceed longest axios timeout (resume-gap analysis can run several minutes).
            proxyReq.setTimeout(660_000)
          })
          proxy.on('proxyRes', (proxyRes) => {
            // Reduce buffering of SSE (text/event-stream) through the dev proxy.
            proxyRes.headers['x-accel-buffering'] = 'no'
          })
        },
      },
    },
  },
})
