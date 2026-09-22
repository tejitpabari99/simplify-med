import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // Vite 7 enforces a dev-server Host allowlist. When this dev server is
    // tunneled (e.g. via ngrok for local end-to-end testing), the request
    // arrives with this Host header and would otherwise be rejected with
    // "Blocked request. This host is not allowed." An exact host is listed
    // here rather than a `.ngrok-free.dev` wildcard, which would let any
    // ngrok tunnel reach this dev server.
    allowedHosts: ['helene-unreconnoitred-overslowly.ngrok-free.dev'],
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
