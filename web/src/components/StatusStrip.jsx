/**
 * The always-visible truth strip (contract §3, design plan §12.1).
 * Presentational only — the shell passes live values in; no fetching here, so it
 * is live-polling-ready by props alone. It is the ambient proof the instrument
 * is alive, air-gapped, and witnessed.
 *
 * Reserved-colour rule: the dot is --verified only when the local origin is
 * reachable (air-gapped-and-alive), --alert only when unreachable. Never
 * decorative.
 */
import { Button } from '@/design-system'

export default function StatusStrip({
  offline = true,
  ledgerLeaves,
  quorum, // { have, need }
  witnessesUp,
  liteMode = false,
  onToggleLite,
  onRoleSwitch,
}) {
  const reachable = offline // `offline` = running air-gapped on the local origin
  const dotColor = reachable ? 'var(--verified)' : 'var(--alert)'
  const have = quorum?.have
  const need = quorum?.need
  const quorumMet = have != null && need != null && have >= need

  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-5)',
        height: 'var(--strip-h)',
        padding: '0 var(--space-4)',
        borderBottom: '1px solid var(--hairline)',
        background: 'var(--bg-panel)',
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--text-xs)',
        color: 'var(--ink-muted)',
        whiteSpace: 'nowrap',
        overflowX: 'auto',
      }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)', color: 'var(--ink)' }}>
        <span
          aria-hidden
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: dotColor,
            boxShadow: reachable ? '0 0 8px -2px var(--verified)' : 'none',
          }}
        />
        {reachable ? 'OFFLINE' : 'UNREACHABLE'} · 127.0.0.1:8443
      </span>
      <Sep />
      <span>ledger {ledgerLeaves ?? '—'} leaves</span>
      <Sep />
      <span style={quorumMet ? { color: 'var(--verified)' } : undefined}>
        quorum {have ?? '—'}/{need ?? '—'}
      </span>
      <Sep />
      <span>{witnessesUp ?? '—'} witnesses up</span>

      <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 'var(--space-2)' }}>
        <Button variant="quiet" size="sm" onClick={onToggleLite} aria-pressed={liteMode}>
          {liteMode ? 'lite: on' : 'lite: off'}
        </Button>
        <Button variant="quiet" size="sm" onClick={onRoleSwitch}>
          switch role
        </Button>
      </span>
    </div>
  )
}

const Sep = () => (
  <span aria-hidden style={{ color: 'var(--ink-faint)' }}>
    ·
  </span>
)
