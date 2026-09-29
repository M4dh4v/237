/**
 * The caveat system (design plan §12.4, sakshya-honesty §4). Small, consistent,
 * never hidden in a tooltip when material. One component, four fixed kinds; the
 * copy is the honesty contract and must not be softened.
 *
 * STUB: props + copy frozen. Lane A styles it; the words stay.
 */
const COPY = {
  'proves-key':
    'This proves which key/device/session decrypted the document. It is strong evidence about a person, not a confession.',
  ranking:
    'At this document length, the collusion code ranks likely colluders; it does not name one at a formal false-positive bound. Longer documents narrow this.',
  'text-domain':
    'Uploaded files become the document body; the mark rides in the text layer, so text-bearing documents trace best.',
  simulated:
    'Parts of this build are simulated and disclosed: witnesses share a host, transport TLS is classical by design (outside the evidence path), the corpus is template prose, the device fingerprint is asserted not attested.',
}

export default function Caveat({ kind }) {
  const text = COPY[kind]
  if (!text) return null
  return (
    <p
      role="note"
      style={{
        display: 'flex',
        gap: 8,
        margin: 0,
        padding: '8px 12px',
        borderLeft: '2px solid var(--accent-soft)',
        background: 'var(--bg-panel)',
        borderRadius: 'var(--radius)',
        color: 'var(--ink-muted)',
        fontSize: 13,
        lineHeight: 1.45,
      }}
    >
      <span aria-hidden style={{ color: 'var(--accent-soft)', fontFamily: 'var(--font-mono)' }}>i</span>
      {text}
    </p>
  )
}
