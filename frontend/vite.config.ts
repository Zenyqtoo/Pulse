import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: API proxied to FastAPI on :8000. Build: output served by FastAPI from backend/static.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 2500,
  },
})
