/**
 * The static poster shown in place of a 3D scene when the machine can't or
 * shouldn't run it: prefers-reduced-motion, manual lite mode, or WebGL failure
 * (sakshya-3d "every scene ships a static fallback"). Each scene supplies its
 * own composed *.static.jsx; this is the shared frame around it / the generic
 * fallback when a name has no poster yet.
 *
 * STUB: props frozen (`name` selects the poster). Real posters are Lane A.
 */
export default function SceneFallback({ name = 'scene' }) {
  return (
    <div
      role="img"
      aria-label={`${name} — static view`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        minHeight: 240,
        border: '1px solid var(--hairline)',
        borderRadius: 'var(--radius)',
        background:
          'radial-gradient(circle at 50% 30%, var(--bg-elevated), var(--bg))',
        color: 'var(--ink-muted)',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
      }}
    >
      <span style={{ color: 'var(--struct-2)' }}>{name}</span>
      <span>static view · lite mode</span>
    </div>
  )
}
