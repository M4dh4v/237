import { lazy, Suspense } from 'react'
import {
  BrowserRouter,
  Routes,
  Route,
  useNavigate,
} from 'react-router-dom'

import { ShellProvider, useRole, useLite } from './shell/context.jsx'
import { StatusStrip, SceneFallback } from './components/index.js'

// Scenes AND dashboards are code-split and lazy-mounted per route (sakshya-3d:
// the landing must never carry a dashboard's weight, and one broken dashboard
// must not white-screen the whole app — its failure stays on its own route).
const Dvarapala = lazy(() => import('./dashboards/Dvarapala.jsx'))
const Suchi = lazy(() => import('./dashboards/Suchi.jsx'))
const Anvesana = lazy(() => import('./dashboards/Anvesana.jsx'))
const Pravaha = lazy(() => import('./scenes/Pravaha.jsx'))
const WitnessRingScene = lazy(() => import('./scenes/WitnessRingScene.jsx'))
// Dev-only design gallery (not linked in product nav).
const Gallery = lazy(() => import('./design-system/Gallery.jsx'))

export default function App() {
  return (
    <ShellProvider>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              <Suspense fallback={null}>
                <Pravaha />
              </Suspense>
            }
          />
          <Route path="/darsana" element={<Darsana />} />
          <Route
            path="/dvarapala"
            element={
              <Authed>
                <div className="stage">
                  <Suspense fallback={<SceneFallback name="Dvārapāla" />}>
                    <Dvarapala />
                  </Suspense>
                </div>
              </Authed>
            }
          />
          <Route
            path="/suchi"
            element={
              <Authed>
                <div className="stage">
                  <Suspense fallback={<SceneFallback name="Sūchī" />}>
                    <Suchi />
                  </Suspense>
                </div>
              </Authed>
            }
          />
          <Route
            path="/anvesana"
            element={
              <Authed>
                <div className="stage">
                  <Suspense fallback={<SceneFallback name="Anveṣaṇa" />}>
                    <Anvesana />
                  </Suspense>
                </div>
              </Authed>
            }
          />
          <Route
            path="/ledger"
            element={
              <Authed>
                <Ledger />
              </Authed>
            }
          />
          <Route
            path="/_ds"
            element={
              <Suspense fallback={null}>
                <Gallery />
              </Suspense>
            }
          />
          <Route
            path="*"
            element={
              <Suspense fallback={null}>
                <Pravaha />
              </Suspense>
            }
          />
        </Routes>
      </BrowserRouter>
    </ShellProvider>
  )
}

/**
 * The frame for every authenticated screen: the always-visible status strip
 * (design plan §12.1) over the routed surface. Ledger values are '—' until a
 * dashboard/Lane wires the live backend reads; the strip is presentational.
 */
function Authed({ children }) {
  const navigate = useNavigate()
  const { lite, toggleLite } = useLite()
  return (
    <div className="shell">
      <div className="shell__strip">
        <StatusStrip
          offline
          ledgerLeaves={undefined}
          quorum={undefined}
          witnessesUp={undefined}
          liteMode={lite}
          onToggleLite={toggleLite}
          onRoleSwitch={() => navigate('/darsana')}
        />
      </div>
      <div className="shell__body">{children}</div>
    </div>
  )
}

/**
 * Darśana — the role threshold (design plan §12.6). Three doors; role select is
 * frictionless UI state, NOT the security model. The god-mode toggle is a
 * labelled demo convenience so one screen can drive all three roles.
 */
const DOORS = [
  { role: 'sender', to: '/dvarapala', name: 'Dvārapāla', sub: 'Sender · seal & distribute' },
  { role: 'recipient', to: '/suchi', name: 'Sūchī', sub: 'Recipient · open & keep' },
  { role: 'investigator', to: '/anvesana', name: 'Anveṣaṇa', sub: 'Investigator · trace to a name' },
]

function Darsana() {
  const navigate = useNavigate()
  const { setRole, godMode, setGodMode } = useRole()

  const enter = (door) => {
    setRole(door.role)
    navigate(door.to)
  }

  return (
    <div className="shell">
      <div className="stage" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 'calc(var(--gap) * 2)' }}>
        <div>
          <h1 style={{ fontSize: 'clamp(28px, 5vw, 44px)' }}>Darśana</h1>
          <p style={{ color: 'var(--ink-muted)', maxWidth: 520 }}>
            Choose a role to enter. This is a demo convenience — a real deployment
            separates these by credential.
          </p>
        </div>

        <div style={{ display: 'flex', gap: 'var(--gap)', flexWrap: 'wrap' }}>
          {DOORS.map((d) => (
            <button
              key={d.role}
              type="button"
              onClick={() => enter(d)}
              style={{
                flex: '1 1 220px',
                textAlign: 'left',
                padding: 'calc(var(--gap) * 1.5)',
                background: 'var(--bg-panel)',
                border: '1px solid var(--hairline)',
                borderRadius: 'var(--radius)',
                color: 'var(--ink)',
                cursor: 'pointer',
              }}
            >
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 20 }}>{d.name}</div>
              <div style={{ color: 'var(--ink-muted)', fontSize: 14, marginTop: 4 }}>{d.sub}</div>
            </button>
          ))}
        </div>

        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 10, color: 'var(--ink-muted)', fontSize: 13 }}>
          <input type="checkbox" checked={godMode} onChange={(e) => setGodMode(e.target.checked)} />
          demo god-mode — drive all three roles from one screen (a real deployment
          separates these by credential)
        </label>
      </div>
    </div>
  )
}

/** Akṣaya Śṛṅkhala — the shared ledger (design plan §10). Lane A routes the
 * real full-scale WitnessRing here; the scene boundary is wired now. */
function Ledger() {
  return (
    <div className="stage">
      <h2 style={{ marginBottom: 'var(--gap)' }}>Akṣaya Śṛṅkhala — the imperishable chain</h2>
      <Suspense fallback={<SceneFallback name="Akṣaya Śṛṅkhala" />}>
        <WitnessRingScene data={undefined} interactive={false} />
      </Suspense>
    </div>
  )
}
