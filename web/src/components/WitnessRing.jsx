/**
 * The witness ring (contract §3, design plan §10.1, sakshya-3d §2).
 *
 * ONE component at three scales — strip (sender pulse), widget (recipient open),
 * full (shared ledger / investigator). This sameness is a truth claim: the
 * recipient and the investigator must provably see the SAME object, so it is
 * literally the same component driven by props, never three lookalikes.
 *
 * STUB: renders a token-styled placeholder sized to the scale; the real R3F ring
 * (instanced nodes, additive glow, tamper beat) is Lane A. Props frozen.
 */
const SIZES = { strip: 48, widget: 220, full: 480 }

export default function WitnessRing({
  scale = 'full',
  data,
  highlightLeaf,
  onInspect,
  interactive = false,
}) {
  const leaves = Array.isArray(data) ? data.length : data?.leaves ?? data?.entries?.length
  const size = SIZES[scale] ?? SIZES.full
  const clickable = interactive && typeof onInspect === 'function'

  return (
    <div
      role={clickable ? 'button' : 'img'}
      aria-label={`witness ring (${scale}) — ${leaves ?? 'no'} leaves`}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? () => onInspect(highlightLeaf ?? null) : undefined}
      style={{
        width: size,
        height: size,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: scale === 'strip' ? 0 : 6,
        border: '1px solid var(--hairline)',
        borderRadius: '50%',
        // structure gradient = "thinking"/structure only, never a hero wash
        background:
          'radial-gradient(circle at 50% 50%, var(--bg-elevated), var(--bg-panel))',
        boxShadow: `inset 0 0 0 1px var(--hairline)`,
        color: 'var(--ink-muted)',
        fontFamily: 'var(--font-mono)',
        fontSize: scale === 'full' ? 13 : 11,
        cursor: clickable ? 'pointer' : 'default',
      }}
    >
      {scale !== 'strip' && (
        <>
          <span style={{ color: 'var(--struct-2)' }}>witness ring</span>
          <span>{leaves ?? '—'} leaves</span>
          {highlightLeaf != null && scale === 'full' ? (
            <span style={{ color: 'var(--accent)' }}>leaf {String(highlightLeaf)}</span>
          ) : null}
        </>
      )}
    </div>
  )
}
