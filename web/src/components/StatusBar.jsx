import { shortHex } from '../format.js'

/**
 * The persistent bar across the top of both tabs.
 *
 * Its job is to answer "is this system currently able to do the thing it
 * claims" at a glance, which is why fail-closed gets equal billing with tree
 * size rather than only appearing when something breaks. A page about a
 * fail-closed system that only mentions the closed state in an error box is
 * telling the reader that failure is exceptional; here it is an expected
 * operating mode and it is on screen permanently as a state, not an alarm.
 */
export default function StatusBar({ demoState, reachable, failClosed, lastError }) {
  const sth = demoState?.sth
  const witnesses = demoState?.witnesses || []
  const witnessSigs = sth?.witness_sigs || {}
  const signed = witnesses.filter((w) => witnessSigs[w])
  const quorum = demoState?.min_witnesses

  // "alive" is not something this page can establish -- it would require
  // contacting each witness port directly. What it can show is how many
  // witnesses co-signed the head it last saw, and it says exactly that.
  const witnessText = reachable === null
    ? '—'
    : !reachable
      ? '—'
      : witnesses.length
        ? `${signed.length} of ${witnesses.length} co-signed the last head` +
          (quorum != null ? ` (quorum ${quorum})` : '')
        : '—'

  return (
    <div className="statusbar" role="status" aria-live="polite">
      <div className="statusbar-item">
        <span className="statusbar-key">backend</span>
        {reachable === null ? (
          <span className="muted">checking…</span>
        ) : reachable ? (
          <span className="ok">reachable · 127.0.0.1:8443</span>
        ) : (
          <span className="bad">not reachable</span>
        )}
      </div>

      <div className="statusbar-item">
        <span className="statusbar-key">tree size</span>
        <span>{sth?.tree_size ?? demoState?.tree_size ?? '—'}</span>
      </div>

      <div className="statusbar-item">
        <span className="statusbar-key">root</span>
        <code title={sth?.root_hash || demoState?.root || ''}>
          {sth?.root_hash
            ? shortHex(sth.root_hash, 10, 6)
            : demoState?.root
              ? shortHex(demoState.root, 10, 6)
              : '—'}
        </code>
      </div>

      <div className="statusbar-item">
        <span className="statusbar-key">witnesses</span>
        <span>{witnessText}</span>
      </div>

      <div className="statusbar-item">
        <span className="statusbar-key">fail-closed</span>
        {failClosed ? (
          <span className="bad">ENGAGED — the last open was refused</span>
        ) : (
          <span className="ok">not engaged this session</span>
        )}
      </div>

      {lastError ? (
        <div className="statusbar-item statusbar-error" title={lastError}>
          {lastError}
        </div>
      ) : null}
    </div>
  )
}
