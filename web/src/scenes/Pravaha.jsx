/**
 * Pravāha ("the flow") — the landing (design plan §6). One continuous scroll
 * journey that makes a stranger feel the idea before reading a feature: one
 * secret file, how it goes out, how the gate works, why many witnesses matter,
 * how a leak is traced home. Lenis drives the scroll; a single 0→1 progress
 * ref drives the one persistent R3F canvas behind the text (PravahaScene).
 *
 * Reduced-motion / lite: the canvas never mounts; each station shows a still
 * motif with the SAME copy, so the narrative reads as static frames.
 *
 * Honesty (sakshya-honesty): "reads as an ordinary copy" (never pixel-identical);
 * "many independent witnesses keep the same ledger" (never blockchain/mining);
 * the certificate row says "present", never "verified".
 */
import { lazy, Suspense, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useLite, useRole } from '@/shell/context.jsx'
import { StatusStrip } from '@/components/index.js'
import useLenisProgress from './useLenisProgress.js'
import StationMotif from './PravahaMotif.jsx'

const PravahaScene = lazy(() => import('./PravahaScene.jsx'))

const STATIONS = [
  {
    id: 'hook',
    wordmark: 'SĀKṢYA',
    deva: 'साक्ष्य',
    title: 'Every copy looks the same. Every copy knows who opened it.',
    align: 'center',
  },
  {
    id: 'crowd',
    kicker: 'the problem',
    body: 'One file. Fifty readers. It leaks. Every copy is identical, so everyone is equally guilty — and no one can be named.',
    align: 'right',
  },
  {
    id: 'gate',
    kicker: 'Dvārapāla · the gate',
    body: 'The key is never released until the recipient’s own post-quantum signature is written to the ledger. Record first, key second. There is no opening without a trace.',
    align: 'left',
  },
  {
    id: 'mark',
    kicker: 'Guptamudrā · the hidden seal',
    body: 'The copy is fingerprinted with a mark grown from that exact ledger entry. Two people open the same file and receive two different hidden marks. It reads as an ordinary copy. It is not.',
    align: 'left',
  },
  {
    id: 'ring',
    kicker: 'Akṣaya Śṛṅkhala · the imperishable chain',
    body: 'The book of who-opened-what is held by many independent witnesses at once — like a private network where everyone keeps the same ledger. Changing one copy means fighting all the others, and every signature here is post-quantum. No single administrator can rewrite history.',
    align: 'right',
  },
  {
    id: 'trace',
    kicker: 'Anveṣaṇa · the investigation',
    body: 'Drop the leaked copy, a screenshot, or a single pasted paragraph. We read the hidden token, match it to the ledger, and return the exact recipient — with proof anyone can check.',
    align: 'left',
  },
]

const DOORS = [
  { role: 'sender', to: '/dvarapala', name: 'Dvārapāla', sub: 'Sender · seal & distribute' },
  { role: 'recipient', to: '/suchi', name: 'Sūchī', sub: 'Recipient · open & keep' },
  { role: 'investigator', to: '/anvesana', name: 'Anveṣaṇa', sub: 'Investigator · trace to a name' },
]

const PRESENT = ['signature present', 'inclusion proof present', 'witness quorum present', 'anchor present']

export default function Pravaha() {
  const navigate = useNavigate()
  const { lite, toggleLite } = useLite()
  const { setRole } = useRole()
  const progress = useRef(0)
  const reduced =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  const poster = lite || reduced

  useLenisProgress(progress, !poster)

  const enter = (door) => {
    setRole(door.role)
    navigate(door.to)
  }

  return (
    <div style={{ position: 'relative', background: 'var(--bg)' }}>
      <div style={{ position: 'fixed', top: 0, left: 0, right: 0, zIndex: 3 }}>
        <StatusStrip
          offline
          ledgerLeaves={0}
          quorum={undefined}
          witnessesUp={undefined}
          liteMode={lite}
          onToggleLite={toggleLite}
          onRoleSwitch={() => navigate('/darsana')}
        />
      </div>

      <Link
        to="/darsana"
        style={{
          position: 'fixed',
          top: 'calc(var(--strip-h) + var(--space-3))',
          right: 'var(--space-4)',
          zIndex: 3,
          fontFamily: 'var(--font-mono)',
          fontSize: 'var(--text-xs)',
          color: 'var(--ink-faint)',
        }}
      >
        skip to app →
      </Link>

      {!poster && (
        <Suspense fallback={null}>
          <PravahaScene progressRef={progress} />
        </Suspense>
      )}

      {STATIONS.map((s) => (
        <Station key={s.id} station={s} poster={poster} />
      ))}

      {/* Station 6 — the proof, and the door (the Darśana threshold) */}
      <section
        style={{
          position: 'relative',
          zIndex: 1,
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 'var(--space-6)',
          padding: '0 clamp(var(--space-5), 6vw, 120px)',
          maxWidth: 1080,
          margin: '0 auto',
        }}
      >
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ amount: 0.5 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        >
          <p style={{ maxWidth: 620, fontSize: 'clamp(20px, 3vw, 30px)', lineHeight: 1.4, color: 'var(--ink)', margin: 0 }}>
            Built to run on a disconnected machine. No cloud. No internet. No
            public chain.
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', marginTop: 'var(--space-4)' }}>
            {PRESENT.map((c) => (
              <span
                key={c}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 'var(--text-xs)',
                  color: 'var(--ink-muted)',
                  border: '1px solid var(--hairline)',
                  borderRadius: 'var(--radius)',
                  padding: '4px 10px',
                }}
              >
                {c}
              </span>
            ))}
          </div>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', color: 'var(--ink-muted)', marginTop: 'var(--space-3)' }}>
            “present”, not “verified” — the browser shows the proof; the standalone verifier checks it.
          </p>
        </motion.div>

        <div>
          <h2 style={{ fontSize: 'clamp(24px, 4vw, 40px)', margin: '0 0 var(--space-2)' }}>Darśana</h2>
          <p style={{ color: 'var(--ink-muted)', margin: '0 0 var(--space-5)', maxWidth: 520 }}>
            Choose a role to enter. A demo convenience — a real deployment separates these by credential.
          </p>
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
        </div>
      </section>
    </div>
  )
}

const ALIGN = {
  left: { alignItems: 'flex-start', textAlign: 'left' },
  right: { alignItems: 'flex-end', textAlign: 'right' },
  center: { alignItems: 'center', textAlign: 'center' },
}

function Station({ station, poster }) {
  const a = ALIGN[station.align] ?? ALIGN.left
  return (
    <section
      style={{
        position: 'relative',
        zIndex: 1,
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: a.alignItems,
        gap: 'var(--space-4)',
        padding: '0 clamp(var(--space-5), 6vw, 120px)',
        pointerEvents: 'none',
      }}
    >
      {poster && (
        <div style={{ width: 'min(420px, 80vw)' }}>
          <StationMotif id={station.id} />
        </div>
      )}
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ amount: 0.6 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        style={{ ...a, display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', maxWidth: station.wordmark ? 900 : 640 }}
      >
        {station.wordmark ? (
          <>
            <span
              lang="sa"
              style={{
                fontSize: 'clamp(20px, 3.4vw, 34px)',
                color: 'var(--struct-2)',
                letterSpacing: '0.04em',
                fontFamily: "'Noto Sans Devanagari', 'Nirmala UI', system-ui, sans-serif",
              }}
            >
              {station.deva}
            </span>
            <h1
              style={{
                fontFamily: 'var(--font-display)',
                fontWeight: 700,
                fontSize: 'clamp(72px, 17vw, 240px)',
                letterSpacing: '-0.04em',
                lineHeight: 0.9,
                margin: 0,
                color: 'var(--ink)',
              }}
            >
              {station.wordmark}
            </h1>
            <p style={{ fontSize: 'clamp(16px, 2.4vw, 24px)', lineHeight: 1.4, color: 'var(--ink-muted)', margin: 'var(--space-2) 0 0', maxWidth: 560 }}>
              {station.title}
            </p>
          </>
        ) : (
          <>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', letterSpacing: '0.12em', color: 'var(--struct-2)', textTransform: 'uppercase' }}>
              {station.kicker}
            </span>
            {station.title ? (
              <h1 style={{ fontSize: 'clamp(32px, 6vw, 68px)', letterSpacing: '-0.02em', lineHeight: 1.05, margin: 0 }}>
                {station.title}
              </h1>
            ) : (
              <p style={{ fontSize: 'clamp(18px, 2.6vw, 26px)', lineHeight: 1.45, color: 'var(--ink)', margin: 0 }}>
                {station.body}
              </p>
            )}
          </>
        )}
      </motion.div>
    </section>
  )
}
