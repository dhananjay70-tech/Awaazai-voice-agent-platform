import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // VoiceAgent only accepts browser WebSocket connections from the origins in its STT_ALLOWED_ORIGINS, which default
  // to http://localhost:5173 and http://127.0.0.1:5173. Failing loudly if 5173 is taken is better than silently
  // moving to 5174, where the voice connection would be refused.
  server: { port: 5173, strictPort: true },
  preview: { port: 5173, strictPort: true },
  // Component tests (`npm run test:ui`). The pure-logic tests (*.test.js) run on Node's own runner (`npm run test:unit`).
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.jsx'],
    setupFiles: ['src/test/setup.js'],
    restoreMocks: true,
  },
})
