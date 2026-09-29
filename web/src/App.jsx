import { lazy, Suspense } from 'react'
import {
  BrowserRouter,
  Routes,
  Route,
  Link,
  useNavigate,
} from 'react-router-dom'

import { ShellProvider, useRole, useLite } from './shell/context.jsx'
import { StatusStrip, SceneFallback } from './components/index.js'
import Dvarapala from './dashboards/Dvarapala.jsx'
import Suchi from './dashboards/Suchi.jsx'
import Anvesana from './dashboards/Anvesana.jsx'

// Scenes are code-split and lazy-mounted per route (sakshya-3d: the landing's
// scene must never run while a dashboard is mounted). The boundaries are wired
// now so Lane A drops real R3F in without touching the shell.
const GateScene = lazy(() => import('./scenes/GateScene.jsx'))
const WitnessRingScene = lazy(() => import('./scenes/WitnessRingScene.jsx'))
// Dev-only design gallery (not linked in product nav).
const Gallery = lazy(() => import('./design-system/Gallery.jsx'))

export default function App() {
  return (
    <ShellProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/darsana" element={<Darsana />} />
          <Route
            path="/dvarapala"
            element={
              <Authed>
                <div className="stage">
                  <Dvarapala />
                </div>
              </Authed>
            }
          />
          <Route
            path="/suchi"
            element={
              <Authed>
                <div className="stage">
                  <Suchi />
                </div>
              </Authed>
            }
          />
          <Route
            path="/anvesana"
            element={
              <Authed>
                <div className="stage">
                  <Anvesana />
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
          <Route path="*" element={<Landing />} />
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
 * Pravāha — the landing (design plan §6). PLACEHOLDER: Lane A builds the
 * scroll journey. Kept truthful and calm; a lazy scene is mounted behind a
 * Suspense boundary so the code-split wiring is real from day one.
 */
function Landing() {
  return (
    <div className="shell">
      <div
        className="stage"
        style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 'calc(var(--gap) * 2)' }}
      >
        <div>
          <p style={{ fontFamily: 'var(--font-mono)', color: 'var(--struct-2)', fontSize: 13, letterSpacing: '0.1em', margin: 0 }}>
            SIH26237 · WESEE · offline forensic-attribution instrument
          </p>
          <h1 style={{ fontSize: 'clamp(40px, 8vw, 88px)', letterSpacing: '-0.02em', margin: '8px 0 0' }}>
            SĀKṢYA
          </h1>
          <p style={{ maxWidth: 560, color: 'var(--ink-muted)', fontSize: 18, lineHeight: 1.5 }}>
            Every copy reads as an ordinary copy, yet quietly carries a different
            hidden fingerprint — and the record of who opened what is held by many
            witnesses, so no single admin can rewrite it.
          </p>
        </div>

        <Suspense fallback={<SceneFallback name="Pravāha — the flow" />}>
          <GateScene />
        </Suspense>

        <div style={{ display: 'flex', gap: 'var(--gap)', alignItems: 'center' }}>
          <Link
            to="/darsana"
            style={{
              padding: '10px 18px',
              borderRadius: 'var(--radius)',
              border: '1px solid var(--accent-soft)',
              color: 'var(--accent)',
              fontFamily: 'var(--font-display)',
              fontWeight: 500,
            }}
          >
            Enter →
          </Link>
          <Link to="/darsana" style={{ color: 'var(--ink-faint)', fontSize: 13 }}>
            skip to app
          </Link>
        </div>
      </div>
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
