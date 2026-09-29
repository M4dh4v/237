/**
 * The always-visible truth strip (contract §3, design plan §12.1).
 * Presentational only — the shell passes live values in. It is the ambient
 * proof the instrument is alive, air-gapped, and witnessed.
 *
 * STUB: real visual polish is Lane A. Props and honesty semantics are frozen.
 */
export default function StatusStrip({
  offline = true,
  ledgerLeaves,
  quorum, // { have, need }
  witnessesUp,
  liteMode = false,
  onToggleLite,
  onRoleSwitch,
}) {
  const dotColor = offline ? 'var(--verified)' : 'var(--alert)'
  const have = quorum?.have
  const need = quorum?.need

  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'calc(var(--gap) * 1.25)',
        height: 'var(--strip-h)',
        padding: '0 var(--gap)',
        borderBottom: '1px solid var(--hairline)',
        background: 'var(--bg-panel)',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        color: 'var(--ink-muted)',
        whiteSpace: 'nowrap',
        overflowX: 'auto',
      }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--ink)' }}>
        <span
          aria-hidden
          style={{ width: 7, height: 7, borderRadius: '50%', background: dotColor }}
        />
        {offline ? 'OFFLINE' : 'UNREACHABLE'} · 127.0.0.1:8443
      </span>
      <Sep />
      <span>ledger {ledgerLeaves ?? '—'} leaves</span>
      <Sep />
      <span>
        quorum {have ?? '—'}/{need ?? '—'}
      </span>
      <Sep />
      <span>{witnessesUp ?? '—'} witnesses up</span>

      <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 'var(--gap)' }}>
        <button type="button" onClick={onToggleLite} style={btn}>
          {liteMode ? 'lite: on' : 'lite: off'}
        </button>
        <button type="button" onClick={onRoleSwitch} style={btn}>
          switch role
        </button>
      </span>
    </div>
  )
}

const Sep = () => <span aria-hidden style={{ color: 'var(--ink-faint)' }}>·</span>

const btn = {
  background: 'transparent',
  border: '1px solid var(--hairline)',
  borderRadius: 'var(--radius)',
  color: 'var(--ink-muted)',
  font: 'inherit',
  padding: '2px 8px',
  cursor: 'pointer',
}
