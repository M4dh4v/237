/**
 * Still motifs for the Pravāha landing on the poster path (lite / reduced-motion
 * / no-WebGL) — one composed SVG per station, token colours only, no GPU. The
 * copy lives in Pravaha.jsx; these carry the visual beat so the story reads as
 * static frames. Honest by construction: no reserved green/red as decoration.
 */
import WitnessRingStatic from '@/components/WitnessRing.static.jsx'

const frame = {
  width: '100%',
  border: '1px solid var(--hairline)',
  borderRadius: 'var(--radius)',
  background: 'radial-gradient(circle at 50% 35%, var(--bg-elevated), var(--bg))',
  display: 'block',
}

export default function StationMotif({ id }) {
  if (id === 'ring') {
    return (
      <div style={{ ...frame, padding: 'var(--space-4)' }}>
        <WitnessRingStatic scale="full" leaves={7} witnesses={5} highlightLeaf={2} />
      </div>
    )
  }

  return (
    <svg viewBox="0 0 320 200" style={{ ...frame, maxWidth: 420, height: 'auto' }} role="img" aria-label={`${id} — still`}>
      {id === 'hook' && (
        <>
          <rect x="130" y="55" width="60" height="80" rx="2" fill="var(--ink-muted)" opacity="0.9" />
          <line x1="140" y1="75" x2="180" y2="75" stroke="var(--bg)" strokeWidth="2" />
          <line x1="140" y1="88" x2="180" y2="88" stroke="var(--bg)" strokeWidth="2" />
          <line x1="140" y1="101" x2="172" y2="101" stroke="var(--bg)" strokeWidth="2" />
        </>
      )}

      {id === 'crowd' &&
        Array.from({ length: 24 }).map((_, i) => {
          const x = 40 + (i % 8) * 32
          const y = 50 + Math.floor(i / 8) * 44
          const leaker = i === 11
          return (
            <rect
              key={i}
              x={x}
              y={y}
              width="20"
              height="28"
              rx="1.5"
              fill={leaker ? 'var(--alert)' : 'var(--ink-faint)'}
              opacity={leaker ? 0.9 : 0.6}
            />
          )
        })}

      {id === 'gate' && (
        <>
          {/* two light bars, parted; the sealed block sits LEFT (record first) */}
          <rect x="120" y="40" width="6" height="120" rx="1" fill="var(--struct-1)" />
          <rect x="194" y="40" width="6" height="120" rx="1" fill="var(--struct-1)" />
          <rect x="60" y="92" width="26" height="18" rx="2" fill="var(--accent)" />
          <line x1="86" y1="101" x2="120" y2="101" stroke="var(--struct-2)" strokeWidth="1.5" opacity="0.7" />
          <rect x="150" y="80" width="20" height="40" rx="2" fill="var(--ink-muted)" opacity="0.8" />
        </>
      )}

      {id === 'mark' && (
        <>
          {/* two pages, same body text, different marked words */}
          <rect x="55" y="45" width="86" height="110" rx="2" fill="var(--ink-muted)" opacity="0.85" />
          <rect x="179" y="45" width="86" height="110" rx="2" fill="var(--ink-muted)" opacity="0.85" />
          {[70, 84, 98, 112, 126].map((y) => (
            <line key={`l${y}`} x1="65" y1={y} x2="131" y2={y} stroke="var(--bg)" strokeWidth="2" />
          ))}
          {[70, 84, 98, 112, 126].map((y) => (
            <line key={`r${y}`} x1="189" y1={y} x2="255" y2={y} stroke="var(--bg)" strokeWidth="2" />
          ))}
          <rect x="90" y="81" width="22" height="6" fill="var(--accent)" />
          <rect x="200" y="95" width="22" height="6" fill="var(--accent)" />
        </>
      )}

      {id === 'trace' && (
        <>
          {/* a skewed leaked page, marked words assembling toward one leaf */}
          <g transform="rotate(-6 110 100)">
            <rect x="70" y="55" width="80" height="100" rx="2" fill="var(--ink-faint)" opacity="0.8" />
            <rect x="86" y="80" width="18" height="6" fill="var(--accent)" />
            <rect x="112" y="96" width="18" height="6" fill="var(--accent)" />
          </g>
          <line x1="150" y1="100" x2="230" y2="100" stroke="var(--accent-soft)" strokeWidth="1.5" strokeDasharray="3 3" />
          <rect x="230" y="86" width="40" height="28" rx="2" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
          <circle cx="250" cy="100" r="4" fill="var(--accent)" />
        </>
      )}
    </svg>
  )
}
