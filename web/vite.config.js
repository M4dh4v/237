import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The proxy exists so the app can call the API with same-origin *relative*
// URLs. That is not a convenience: the backend runs on plain HTTP at
// 127.0.0.1:8443 when started with --no-tls, and a page served from
// https:// would have its cross-origin requests blocked outright, with no
// useful error in the console. Relative URLs sidestep the whole class of
// problem, and they also mean no base URL is baked into the bundle -- the
// built assets work unchanged whether they are served by Vite, by the demo
// server, or from a file.
//
// target is 127.0.0.1 rather than "localhost" on purpose. "localhost" can
// resolve to ::1 first, and the demo server binds IPv4; that mismatch shows
// up as ECONNREFUSED that looks like "the backend is down" when it is not.
const BACKEND = 'http://127.0.0.1:8443'

const proxied = [
  '/demo',
  '/leakcheck',
  '/ledger',
  '/witnesses',
  '/health',
  '/documents',
  '/open',
  '/anchors',
]

const proxy = Object.fromEntries(
  proxied.map((path) => [path, { target: BACKEND, changeOrigin: false }]),
)

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy,
  },
  build: {
    // Vite's default warning threshold is tuned for apps that split vendor
    // chunks. This one is deliberately a single small bundle; the warning
    // would be noise on every build.
    chunkSizeWarningLimit: 900,
  },
})
