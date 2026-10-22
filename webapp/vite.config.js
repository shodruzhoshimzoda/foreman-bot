import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// В разработке /api проксируется на бот (python -m bot.main, порт WEB_PORT).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8080' } },
  build: { target: 'es2019', sourcemap: false, chunkSizeWarningLimit: 300 },
})
