import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev the backend runs separately (`mtgdm serve --reload`); Vite proxies the API to it.
const backend = process.env.MTGDM_BACKEND ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
    },
  },
})
