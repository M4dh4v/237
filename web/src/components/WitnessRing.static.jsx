/**
 * WitnessRing static poster (sakshya-3d "every scene ships a static fallback").
 * Rendered in place of the R3F canvas on lite mode, prefers-reduced-motion, or
 * no WebGL — SVG only, no GPU, no external asset. Same three scales, same idea,
 * same honest caption, so the pitch reads identically on a weak laptop.
 *
 * Honest framing (sakshya-honesty §6): "many independent witnesses co-sign a
 * shared, append-only ledger" — never "blockchain / mining / coin".
 */
const R = 78 // ring radius in the 200-box viewBox

function ringNodes(n) {
  const pts = []
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2
    pts.push([100 + Math.cos(a) * R, 100 + Math.sin(a) * R])
  }
  return pts
}

export default function WitnessRingStatic({
  scale = 'full',
  leaves = 0,
  witnesses = 3,
  highlightLeaf,
}) {
  const nodes = ringNodes(Math.max(2, witnesses))
  const blocks = Math.max(1, Math.min(leaves || 1, 5)) // chain head, a few blocks
  const isStrip = scale === 'strip'
  const boxSize = { strip: 48, widget: 220, full: 480 }[scale] ?? 480

  const svg = (
    <svg
      viewBox="0 0 200 200"
      width={scale === 'full' ? '100%' : boxSize}
      height={scale === 'full' ? undefined : boxSize}
      style={{ maxWidth: boxSize, height: 'auto', display: 'block' }}
      role="img"
      aria-label={`witness ring — ${leaves} leaves held by ${witnesses} witnesses`}
    >
      {/* the ring: witnesses linked to one another (all hold the same book) */}
      <polygon
        points={nodes.map((p) => p.join(',')).join(' ')}
        fill="none"
        stroke="var(--struct-1)"
        strokeWidth="0.75"
        opacity="0.35"
      />
      {/* spokes: each witness co-signs the shared chain head at the centre */}
      {nodes.map((p, i) => (
        <line
          key={`s${i}`}
          x1={p[0]}
          y1={p[1]}
          x2="100"
          y2="100"
          stroke="var(--struct-2)"
          strokeWidth="0.6"
          opacity="0.45"
        />
      ))}
      {/* the chain head — a short append-only stack of blocks */}
      {!isStrip &&
        Array.from({ length: blocks }).map((_, i) => {
          const hi = highlightLeaf != null && Number(highlightLeaf) === i
          const x = 100 + (i - (blocks - 1) / 2) * 13
          return (
            <rect
              key={`b${i}`}
              x={x - 5}
              y={94}
              width={10}
              height={12}
              rx={1.5}
              fill={hi ? 'var(--accent)' : 'var(--ink-faint)'}
              stroke={hi ? 'var(--accent)' : 'var(--hairline)'}
              strokeWidth="0.5"
            />
          )
        })}
      {isStrip && <circle cx="100" cy="100" r="6" fill="var(--ink-faint)" />}
      {/* witness nodes */}
      {nodes.map((p, i) => (
        <circle
          key={`n${i}`}
          cx={p[0]}
          cy={p[1]}
          r={isStrip ? 5 : 4.5}
          fill="var(--struct-1)"
        />
      ))}
    </svg>
  )

  if (isStrip) return svg

  return (
    <div style={{ display: 'grid', placeItems: 'center', gap: 'var(--space-3)' }}>
      {svg}
      {scale === 'full' && (
        <p
          style={{
            margin: 0,
            maxWidth: 420,
            textAlign: 'center',
            color: 'var(--ink-muted)',
            fontSize: 'var(--text-sm)',
            lineHeight: 1.5,
          }}
        >
          {witnesses} independent witnesses co-sign a shared, append-only ledger —
          {leaves ? ` ${leaves} leaves` : ' the record'} held by all, so no single
          admin can rewrite it.
        </p>
      )}
    </div>
  )
}
