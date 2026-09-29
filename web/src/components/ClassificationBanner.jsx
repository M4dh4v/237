/**
 * The classification banner (design plan §11, §7.3). A thin, unmissable strip
 * naming the document's classification, pinned top or bottom. Neutral by
 * default — it is a label, not an alert, so it does not spend the reserved
 * colours.
 *
 * STUB: props frozen. `caveat` is optional trailing text (e.g. handling note).
 */
export default function ClassificationBanner({ level, position = 'top', caveat }) {
  return (
    <div
      style={{
        position: 'sticky',
        [position]: 0,
        zIndex: 5,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 'var(--gap)',
        padding: '4px var(--gap)',
        borderTop: position === 'bottom' ? '1px solid var(--hairline)' : 'none',
        borderBottom: position === 'top' ? '1px solid var(--hairline)' : 'none',
        background: 'var(--bg-elevated)',
        color: 'var(--ink)',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
      }}
    >
      <span>{level || 'UNCLASSIFIED'}</span>
      {caveat ? <span style={{ color: 'var(--ink-muted)', letterSpacing: 0, textTransform: 'none' }}>{caveat}</span> : null}
    </div>
  )
}
