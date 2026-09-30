import { Pill } from '../_shared/ui.jsx'

/**
 * The four-step spine (design plan §7.0): source → recipients → classification →
 * seal. It is both navigation and progress — you always know where you are. One
 * accent (the current step glows gold); completed steps go structure-cyan.
 */
const STEPS = [
  { id: 'source', n: 1, name: 'Source', sub: 'what to seal' },
  { id: 'recipients', n: 2, name: 'Recipients', sub: 'who is included' },
  { id: 'classification', n: 3, name: 'Classification', sub: 'how it is marked' },
  { id: 'seal', n: 4, name: 'Seal', sub: 'arm & distribute' },
]

export { STEPS }

export default function StepRail({ current, reached, onGo }) {
  const currentIdx = STEPS.findIndex((s) => s.id === current)
  return (
    <nav
      aria-label="sealing steps"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        width: '100%',
      }}
    >
      <div style={{ padding: '0 6px 10px', borderBottom: '1px solid var(--hairline)', marginBottom: 6 }}>
        <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 18 }}>Dvārapāla</div>
        <div style={{ color: 'var(--ink-muted)', fontSize: 12, marginTop: 2 }}>the gate · one deliberate act</div>
      </div>
      {STEPS.map((s, i) => {
        const done = i < currentIdx
        const now = i === current || s.id === current
        const canGo = reached.has(s.id)
        const cls = `lb-step ${done ? 'lb-step--done' : ''} ${now ? 'lb-step--now' : ''}`
        return (
          <button
            key={s.id}
            type="button"
            className={cls}
            disabled={!canGo}
            onClick={() => canGo && onGo(s.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              textAlign: 'left',
              background: now ? 'var(--bg-panel)' : 'transparent',
              border: '1px solid ' + (now ? 'var(--hairline)' : 'transparent'),
              borderRadius: 'var(--radius)',
              padding: '10px 10px',
              cursor: canGo ? 'pointer' : 'default',
              color: now ? 'var(--ink)' : done ? 'var(--ink-muted)' : 'var(--ink-faint)',
              opacity: canGo ? 1 : 0.6,
            }}
          >
            <span
              className="lb-step__dot"
              aria-hidden
              style={{
                width: 26,
                height: 26,
                flex: '0 0 26px',
                display: 'grid',
                placeItems: 'center',
                borderRadius: '50%',
                border: '1px solid var(--hairline)',
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                color: now ? 'var(--bg)' : 'inherit',
              }}
            >
              {done ? '✓' : s.n}
            </span>
            <span style={{ flex: 1 }}>
              <span style={{ display: 'block', fontWeight: 500, fontSize: 14 }}>{s.name}</span>
              <span style={{ display: 'block', fontSize: 12, color: 'var(--ink-faint)' }}>{s.sub}</span>
            </span>
            {now ? <Pill tone="accent">now</Pill> : null}
          </button>
        )
      })}
    </nav>
  )
}
