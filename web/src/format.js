// Small shared presentational helpers. Deliberately not a component library.

/**
 * Truncate a hex string for display while keeping the whole value reachable.
 *
 * The full value is what a user would paste into the standalone verifier, so
 * it must never be destroyed -- truncation is a display choice and the title
 * attribute is the escape hatch. This is why the helper returns the parts
 * rather than a clipped string: callers render <code title={full}>{short}</code>.
 */
export function shortHex(value, head = 12, tail = 8) {
  if (typeof value !== 'string') return String(value ?? '')
  if (value.length <= head + tail + 1) return value
  return `${value.slice(0, head)}…${value.slice(-tail)}`
}

/** Fixed-width percentage for a 0..1 confidence, or null when not a number. */
export function pct(x) {
  if (typeof x !== 'number' || Number.isNaN(x)) return null
  return `${(x * 100).toFixed(1)}%`
}

export function clamp01(x) {
  if (typeof x !== 'number' || Number.isNaN(x)) return 0
  return Math.min(1, Math.max(0, x))
}

/** ISO timestamp -> short local-ish display, never throwing on junk. */
export function when(value) {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return String(value)
  return d.toISOString().replace('T', ' ').replace('Z', 'Z')
}

/**
 * Parse the `leaf` field of a ledger entry.
 *
 * `leaf` arrives as the JSON text of the signed decryption request, not as an
 * object, because the bytes that were hashed are the point. We parse for
 * display only and keep the raw string alongside it so the page can still
 * show something if the shape is unexpected -- swallowing a parse failure here
 * would hide a real contract mismatch behind an empty panel.
 */
export function parseLeaf(leaf) {
  if (leaf == null) return { parsed: null, raw: null, error: 'no leaf was returned' }
  if (typeof leaf === 'object') return { parsed: leaf, raw: null, error: null }
  try {
    return { parsed: JSON.parse(leaf), raw: String(leaf), error: null }
  } catch {
    return { parsed: null, raw: String(leaf), error: 'the leaf is not parseable as JSON' }
  }
}
