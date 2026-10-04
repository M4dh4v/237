// pm2 deployment for SĀKṢYA.
//
// Two processes, matching how the project is actually built to run (see the
// comment above `demo-serve` in the Makefile): the authority API binds 8443,
// and the console is served on 7891. There is deliberately no bundled server
// for the console, and this deployment does not invent one -- it runs the real
// `vite build` output through `vite preview`, which is the one bundled server
// that also proxies the API paths.
//
// That proxy is not optional. web/src/api.js calls the API with same-origin
// *relative* URLs (/demo, /leakcheck, ...), so whatever serves the bundle must
// also forward those paths to 127.0.0.1:8443. A plain static server (e.g.
// `serve -s dist`) would answer them with 404s and the console would show
// "backend not reachable" while the backend was up. `vite preview` inherits
// `server.proxy` from vite.config.js, so the built bundle works unchanged.
//
// Data directory: the backend writes its deployment (keys, anchors, ledger)
// into --data. demo-data/ is git-tracked, so this points at /tmp/logfirst-demo
// instead, the same default run.sh uses. Override with DATA=... pm2 restart.
// NOTE: never add --fresh here -- it wipes the deployment on every restart.

const REPO = '/home/madhav/sih/237'
const WEB = `${REPO}/web`

// The project's deps live in a venv, not the system Python: Ubuntu 26.04 ships
// an externally-managed python3 with no pip at all, so `pip install` there is
// refused outright. run.sh assumes a system interpreter; this deployment does
// not, so it names the venv's python explicitly.
const PYTHON = process.env.PYTHON || `${REPO}/.venv/bin/python`

const API_PORT = process.env.API_PORT || '8443'
const WEB_PORT = process.env.WEB_PORT || '7891'
const DATA = process.env.DATA || '/tmp/logfirst-demo'
const WORDS = process.env.WORDS || '1800'

module.exports = {
  apps: [
    {
      name: 'sakshya-api',
      cwd: REPO,
      script: `${REPO}/scripts/demo.py`,
      interpreter: PYTHON,
      args: [
        '--serve',
        '--host', '127.0.0.1',
        '--port', API_PORT,
        '--data', DATA,
        '--words', WORDS,
      ].join(' '),
      // The backend spawns the witness processes itself and is the only thing
      // that reaps them; give it room to shut them down cleanly on restart,
      // otherwise a stale witness keeps holding its 9101+ port and the next
      // start refuses to come up (the failure run.sh's kill_stale guards).
      kill_timeout: 15000,
      autorestart: true,
      max_restarts: 10,
      // Tells demo.py it may let the console's reset control stop the process
      // and have it come back (fresh, via the RESET_REQUESTED sentinel).
      // pm2 already injects pm_id; this names the capability explicitly so it
      // survives a move to another supervisor. Never set it for an unmanaged
      // foreground run -- nothing would restart the server.
      env: { SAKSHYA_SUPERVISED: '1' },
    },
    {
      name: 'sakshya-ui',
      cwd: WEB,
      // Invoke vite directly rather than via `npm run preview`: with npm, pm2
      // manages the npm wrapper and the actual vite server is its child, which
      // can outlive a stop/restart and leave 7891 held.
      script: `${WEB}/node_modules/vite/bin/vite.js`,
      interpreter: 'node',
      // host is set here too (not only in vite.config.js) so the bound address
      // is visible in `pm2 describe` rather than hidden in a config file.
      args: 'preview --host 0.0.0.0 --port ' + WEB_PORT + ' --strictPort',
      autorestart: true,
      max_restarts: 10,
    },
  ],
}
