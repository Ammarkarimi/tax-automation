import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'node:fs'

// Optional local HTTPS: run ../scripts/gen-dev-cert.sh first.
const certDir = new URL('../certs/', import.meta.url)
const https =
  fs.existsSync(new URL('dev-key.pem', certDir)) && process.env.VITE_HTTPS !== 'false'
    ? { key: fs.readFileSync(new URL('dev-key.pem', certDir)), cert: fs.readFileSync(new URL('dev-cert.pem', certDir)) }
    : undefined

const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    https,
    // Same-origin proxy: the refresh-token cookie stays first-party & SameSite=Strict.
    proxy: { '/api': { target: API_TARGET, changeOrigin: true, secure: false } },
    headers: {
      'X-Frame-Options': 'DENY',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
    },
  },
})
