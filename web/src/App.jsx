import { useCallback, useEffect, useRef, useState } from 'react'
import { api, isUnreachable } from './api.js'
import StatusBar from './components/StatusBar.jsx'
import ActRail from './components/ActRail.jsx'
import DistributeOpen from './components/DistributeOpen.jsx'
import LeakCheck from './components/LeakCheck.jsx'
import TamperAct from './components/TamperAct.jsx'
import RobustnessAct from './components/RobustnessAct.jsx'
import OpenContainer from './components/OpenContainer.jsx'
import Users from './components/Users.jsx'
import LedgerGraph from './components/LedgerGraph.jsx'
import { SthPanel, SimulatedPanel } from './components/LedgerView.jsx'

const POLL_MS = 15000

/**
 * The whole demo as one flow, read top to bottom.
 *
 * There used to be four tabs, one per screen, and the story lived in whoever
 * was driving them. Now the three acts of the walkthrough are on one page in
 * order -- distribute a document and attribute a leak of it, tamper with the
 * ledger and watch it caught, then the measured robustness and the one limit
 * that is not hidden -- with a thin rail to jump between them. The two
 * remaining screens that are not part of the narrated demo (opening a handed-in
 * container, and the recipient register) are kept, folded into an appendix, so
 * nothing is lost and nothing competes with the story.
 */
export default function App() {
  const [demoState, setDemoState] = useState(null)
  const [stateError, setStateError] = useState(null)
  // null means "we have not heard back yet". Starting at `true` would render
  // "reachable" before anything has been checked, which is the one claim this
  // bar must not make falsely for even a moment.
  const [reachable, setReachable] = useState(null)
  const [failClosed, setFailClosed] = useState(null)
  const [lastError, setLastError] = useState(null)
  const abort = useRef(null)

  const loadState = useCallback(async () => {
    abort.current?.abort()
    const controller = new AbortController()
    abort.current = controller
    try {
      const s = await api.demoState()
      setDemoState(s)
      setStateError(null)
      setReachable(true)
      setLastError(null)
    } catch (e) {
      if (e?.name === 'AbortError') return
      // A poll that fails after a successful load is a different event from a
      // cold start that fails: the first means the backend went away mid-use.
      // Both set `reachable` false, but only an unreachable backend clears the
      // last-known state, because stale state rendered as current state is the
      // thing that would mislead.
      if (isUnreachable(e)) {
        setReachable(false)
        setDemoState(null)
      }
      setStateError(e)
      setLastError(e.message)
    }
  }, [])

  useEffect(() => {
    loadState()
    const id = setInterval(loadState, POLL_MS)
    return () => {
      clearInterval(id)
      abort.current?.abort()
    }
  }, [loadState])

  const sim = demoState?.simulated

  return (
    <div className="app">
      <header className="app-header">
        <h1>logfirst</h1>
        <p className="subtitle">
          A document cannot be decrypted until the recipient's own
          post-quantum signature is committed to a witness-co-signed
          transparency ledger. The mark on the copy they keep is derived from
          that entry.
        </p>
      </header>

      <StatusBar
        demoState={demoState}
        reachable={reachable}
        failClosed={Boolean(failClosed)}
        lastError={lastError}
      />

      <ActRail />

      {!reachable && stateError ? (
        <div className="panel result-bad">
          <h4>the demo backend is not reachable</h4>
          <p className="mono">{stateError.message}</p>
          <p className="note">
            Act I needs it — start it with{' '}
            <code>python scripts/demo.py --serve</code>. Acts II and III below
            read from the numbers this system produces and are shown regardless.
          </p>
        </div>
      ) : null}

      {reachable && demoState && demoState.available === false ? (
        <div className="panel panel-warn">
          <h4>no scenario is attached to this server</h4>
          <p className="note">
            The server answered, and reported that it is running without a
            scenario: <code>{demoState.reason || 'no reason given'}</code>. The
            demo routes are only registered when a scenario is attached, so
            Act I has nothing to drive. The key-authority routes (/health,
            /ledger/*, /witnesses) may still be up.
          </p>
        </div>
      ) : null}

      <section id="act-live" className="act">
        <h2 className="act-title">
          <span className="act-num">Act I</span>
          Distribute a document, decrypt it, and attribute a leak of it
        </h2>
        <p className="act-lede">
          Seal a document and hand it out; a granted recipient opens it, which is
          what writes the signed block to the ledger and marks their copy;
          download and open that copy; then paste or drop a leak of it and watch
          it trace back to the entry.
        </p>
        <DistributeOpen
          demoState={demoState}
          onSessionChanged={loadState}
          onFailClosed={setFailClosed}
          onOpenSucceeded={() => setFailClosed(null)}
          onError={setLastError}
        />
        <section className="panel panel-truth">
          <h3>The ledger, as a chain</h3>
          <p className="note">
            Each opened document appends one leaf here. Watch a node arrive when a
            recipient decrypts: that append, co-signed by the witness quorum, is
            the event that released the key.
          </p>
          <LedgerGraph demoState={demoState} onError={setLastError} />
        </section>
        <LedgerFooter demoState={demoState} />
        <div className="act-step-break">
          <span>then — take a leak of that copy and trace it</span>
        </div>
        <LeakCheck demoState={demoState} onError={setLastError} onFailClosed={setFailClosed} />
      </section>

      <section id="act-tamper" className="act">
        <h2 className="act-title">
          <span className="act-num">Act II</span>
          Tamper with a committed block
        </h2>
        <TamperAct />
      </section>

      <section id="act-robustness" className="act">
        <h2 className="act-title">
          <span className="act-num">Act III</span>
          Robustness numbers, and one honest limit
        </h2>
        <RobustnessAct />
      </section>

      {/* Rendered once, at the app level, so it sits under the whole flow. */}
      {sim?.length ? <SimulatedPanel simulated={sim} /> : null}

      <details className="details appendix">
        <summary>Appendix — open a handed-in .lfdoc, and the recipient register</summary>
        <p className="note">
          Neither is part of the narrated demo. They are here because they are
          real screens the system exposes: proving a sealed container cannot be
          read without the authority, and the one lever that changes behaviour
          (revoke).
        </p>
        <OpenContainer
          demoState={demoState}
          onSessionChanged={loadState}
          onFailClosed={setFailClosed}
          onOpenSucceeded={() => setFailClosed(null)}
          onError={setLastError}
        />
        <Users onError={setLastError} onChanged={loadState} />
      </details>
    </div>
  )
}

/**
 * The ledger's public face, at the foot of Act I's distribute-and-open.
 *
 * Collapsed by default: it is reference material for reading the head and the
 * anchors, not part of the story. It reuses the same SthPanel as the open flow
 * on purpose, so the head shown here and the head a receipt was committed under
 * are rendered by identical code -- if they ever disagree, the reader sees it
 * without having to compare two presentations.
 */
function LedgerFooter({ demoState }) {
  const anchors = demoState?.anchors || []
  if (!demoState?.sth && anchors.length === 0) return null

  return (
    <details className="details">
      <summary>current ledger head and published anchors</summary>
      <SthPanel
        sth={demoState.sth}
        witnesses={demoState.witnesses}
        witnessPubs={demoState.ledger_publics?.witness_pubs}
        quorum={demoState.min_witnesses}
        title="Head as of the last poll"
      />
      {anchors.length ? (
        <section className="panel">
          <h4>Published anchors</h4>
          <p className="note">
            Roots published outside the log, so a rewrite of history has to
            contradict a record this system does not control.
          </p>
          <table className="table">
            <thead>
              <tr>
                <th>tree size</th>
                <th>root</th>
                <th>timestamp</th>
              </tr>
            </thead>
            <tbody>
              {anchors.map((a, i) => (
                <tr key={i}>
                  <td>{a.tree_size}</td>
                  <td>
                    <code title={a.root_hash}>{String(a.root_hash || '').slice(0, 20)}…</code>
                  </td>
                  <td>{a.timestamp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        <section className="panel">
          <p className="note">no anchors have been published in this scenario</p>
        </section>
      )}
    </details>
  )
}
