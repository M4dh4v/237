/**
 * The single most important honesty rule (design plan §12.3, sakshya-honesty §1).
 * The browser cannot verify a post-quantum signature, so it never prints
 * "valid"/"verified". It says "present, as received" and points at the
 * independent verifier. A calm chip — never alarming, never green.
 *
 * STUB: props frozen (`inline` compacts it for use beside a proof line).
 */
export default function PresentNotVerified({ inline = false }) {
  return (
    <span
      style={{
        display: inline ? 'inline-flex' : 'flex',
        alignItems: 'center',
        gap: 8,
        maxWidth: inline ? undefined : 520,
        padding: inline ? '2px 8px' : '8px 12px',
        border: '1px solid var(--hairline)',
        borderRadius: 'var(--radius)',
        background: 'var(--bg-panel)',
        color: 'var(--ink-muted)',
        fontSize: inline ? 12 : 13,
        lineHeight: 1.45,
      }}
    >
      <strong style={{ color: 'var(--ink)', fontWeight: 500, whiteSpace: 'nowrap', flexShrink: 0 }}>present, as received</strong>
      {inline ? null : (
        <span>
          — the browser shows the proof but cannot verify post-quantum signatures.
          Independent verification is the standalone <code>verifier/</code>.
        </span>
      )}
    </span>
  )
}
