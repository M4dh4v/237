import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

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
  resolve: {
    // `@` -> web/src, the import root every lane uses (contract §3).
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 7891,
    strictPort: true,
    // Vite rejects requests whose Host header it does not recognise, which is
    // what "Blocked request. This host is not allowed" was. The console is
    // reached at saksya.tech through a reverse proxy, so the Host header that
    // arrives here is that domain, not the bind address. `true` allows any
    // host, which is what we want: this listens on 0.0.0.0 by design and is
    // already reachable from the network. The check would only matter for a
    // server exposed to the open internet with DNS pointing elsewhere, and the
    // DNS-rebinding it guards against is not the threat model here.
    allowedHosts: true,
    proxy,
  },
  // `vite preview` serves the built dist/ -- it is what the pm2 deployment
  // runs, since there is no bundled server for the console. The port is set
  // explicitly because preview's default (4173) is not server.port; the proxy
  // is inherited from server.proxy, which is the whole reason the built bundle
  // still reaches the API on 8443 through same-origin relative URLs.
  //
  // host 0.0.0.0 matches what `npm run dev` already binds, so the console is
  // reachable from other hosts on the network. The API stays bound to
  // 127.0.0.1:8443 -- the proxy target is server-side, so those API paths are
  // reachable *through* this server but the backend itself is not exposed.
  preview: {
    host: '0.0.0.0',
    port: 7891,
    strictPort: true,
    allowedHosts: true, // same reasoning as server.allowedHosts above
    proxy,
  },
  build: {
    // Vite's default warning threshold is tuned for apps that split vendor
    // chunks. This one is deliberately a single small bundle; the warning
    // would be noise on every build.
    chunkSizeWarningLimit: 900,
  },
})
