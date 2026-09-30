import Caveat from '@/components/Caveat.jsx'

/**
 * The watermark-capacity meter (design plan §7.1). Turns a real limitation into
 * a credible, visible number: how many mark positions this text carries versus
 * the ~1201 the formal Tardos bound wants. Green when ample, amber when thin —
 * and amber is honest structure-amber via --accent-soft, NOT the reserved alert
 * red (thin text is a limitation, not a failure).
 */
export default function CapacityMeter({ capacity, showCaveat = false }) {
  if (!capacity) return null
  const positions = capacity.positions ?? capacity.tardos_positions ?? 0
  const needed = capacity.needed ?? capacity.tardos_required ?? 1201
  const ratio = needed > 0 ? Math.min(1, positions / needed) : 0
  const ample = positions >= needed
  // ample -> structure cyan (plenty); thin -> soft accent (attention, not alarm)
  const barColor = ample ? 'var(--struct-2)' : 'var(--accent-soft)'

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <span style={{ fontSize: 12, color: 'var(--ink-muted)' }}>watermark capacity</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink)' }}>
          {positions} / {needed} positions
        </span>
      </div>
      <div
        role="meter"
        aria-valuenow={positions}
        aria-valuemin={0}
        aria-valuemax={needed}
        aria-label="watermark mark positions available"
        style={{
          height: 6,
          borderRadius: 6,
          background: 'var(--bg)',
          border: '1px solid var(--hairline)',
          overflow: 'hidden',
        }}
      >
        <div style={{ width: '100%', height: '100%', background: barColor, transformOrigin: 'left', transform: `scaleX(${ratio})`, transition: 'transform var(--dur-slow) var(--ease-out)' }} />
      </div>
      <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.45 }}>
        {ample
          ? 'Ample text — attribution is strong and formally bounded.'
          : capacity.strength ||
            'Thin text — enough to rank a likely source, short of the formal false-positive bound. More text narrows it.'}
      </p>
      {showCaveat ? <div style={{ marginTop: 10 }}><Caveat kind="text-domain" /></div> : null}
    </div>
  )
}
