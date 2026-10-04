import { useEffect, useRef, useState } from 'react'
import { api, isUnreachable } from '@/api.js'
import { Button, mono, ZoneLabel } from '../_shared/ui.jsx'
import { Loading } from '../_shared/Async.jsx'

/**
 * The demo-sandbox reset (design plan §1, rule 2; sakshya-honesty §6).
 *
 * The one control that returns the demo to a clean state between runs. It is
 * built to never read as an authority capability, because the product's whole
 * claim is that no single administrator can rewrite the witnessed record: this
 * restarts the *operator's own demo instance* from seed, and the copy says so.
 *
 * The backend (`POST /demo/admin/reset`) is demo-gated -- absent on a
 * production-shaped run -- and refuses outright when the instance is not
 * supervised, because killing a foreground server nobody can bring back would
 * just leave the console dark. That refusal is surfaced here as its own honest
 * state with the exact command, not as an error.
 *
 * Colour note: the destructive act uses the ordinary button, never alert-red.
 * Red is reserved for a real failure or an unknown source; a reset the operator
 * asked for is neither.
 */

const CONFIRM_COPY =
  'Rebuild this demo sandbox from seed — new keys, fresh witnesses, an empty ledger, the ' +
  'curated documents back. This discards the running demo instance. It is an operator ' +
  'action on your own sandbox, not a capability of the authority: in a real deployment ' +
  'no single administrator can clear the witnessed ledger.'

const STEPS = [
  'stopping the old witnesses',
  'reseeding the deployment',
  'restarting the instance',
]

const RETURN_TIMEOUT_MS = 45000

export default function DemoReset() {
  // idle | confirm | running | waiting | back | unsupervised | timeout | error
  const [phase, setPhase] = useState('idle')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const alive = useRef(true)
  useEffect(() => () => { alive.current = false }, [])

  // The instance goes away and comes back during a reset, so "did it return?"
  // is answered by polling /health, not by the reset response alone.
  const waitForReturn = () => {
    const started = Date.now()
    const tick = async () => {
      if (!alive.current) return
      try {
        await api.health()
      } catch {
        if (!alive.current) return
        if (Date.now() - started > RETURN_TIMEOUT_MS) { setPhase('timeout'); return }
        setTimeout(tick, 1000)
        return
      }
      if (!alive.current) return
      setPhase('back')
      setTimeout(() => { if (alive.current) window.location.reload() }, 1200)
    }
    tick()
  }

  const run = async () => {
    setPhase('running'); setError(null); setResult(null)
    let data
    try {
      data = await api.resetDemo()
    } catch (e) {
      // The instance may drop the connection as it restarts — that is the
      // restart succeeding, not the request failing, so wait rather than
      // reporting an error the operator would then retry into a live server.
      if (isUnreachable(e)) { setPhase('waiting'); waitForReturn(); return }
      setError(e); setPhase('error'); return
    }
    setResult(data)
    if (!data?.rebuilding) { setPhase('unsupervised'); return }
    setPhase('waiting'); waitForReturn()
  }

  return (
    <section
      style={{
        border: '1px solid var(--hairline)',
        borderRadius: 'var(--radius)',
        background: 'var(--bg-panel)',
        padding: 'var(--gap)',
      }}
    >
      <ZoneLabel>demo sandbox</ZoneLabel>

      {phase === 'idle' ? (
        <>
          <p style={{ margin: '8px 0 var(--gap)', fontSize: 12, color: 'var(--ink-faint)', lineHeight: 1.5 }}>
            This console is a demo instance. Resetting reseeds it from scratch.
          </p>
          <Button onClick={() => setPhase('confirm')}>Reset demo sandbox</Button>
        </>
      ) : null}

      {phase === 'confirm' ? (
        <>
          <p style={{ margin: '8px 0 var(--gap)', fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
            {CONFIRM_COPY}
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button onClick={run}>Rebuild from seed</Button>
            <Button variant="quiet" onClick={() => setPhase('idle')}>Cancel</Button>
          </div>
        </>
      ) : null}

      {phase === 'running' ? (
        <div style={{ marginTop: 8 }}>
          <Loading steps={STEPS} activeStep={1} />
        </div>
      ) : null}

      {phase === 'waiting' ? (
        <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
          Reseeding from seed — the witnesses are restarting. This console reloads
          when the instance is back.
        </p>
      ) : null}

      {phase === 'back' ? (
        <p style={{ margin: '8px 0 0', fontSize: 12, color: 'var(--ink)', lineHeight: 1.5 }}>
          Sandbox is back — reloading…
        </p>
      ) : null}

      {phase === 'unsupervised' ? (
        <>
          <p style={{ margin: '8px 0', fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
            {result?.note}
          </p>
          {result?.command ? (
            <pre
              style={{
                ...mono, fontSize: 11, margin: '0 0 var(--gap)', padding: '8px 10px',
                background: 'var(--bg)', border: '1px solid var(--hairline)',
                borderRadius: 'var(--radius)', overflowX: 'auto', whiteSpace: 'pre-wrap',
              }}
            >
              {result.command}
            </pre>
          ) : null}
          <Button variant="quiet" onClick={() => setPhase('idle')}>Close</Button>
        </>
      ) : null}

      {phase === 'timeout' ? (
        <>
          <p style={{ margin: '8px 0 var(--gap)', fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
            The instance has not answered for 45 seconds. Check the supervisor
            (<span style={mono}>pm2 status</span>) and the API log, then reload.
          </p>
          <Button variant="quiet" onClick={() => window.location.reload()}>Reload</Button>
        </>
      ) : null}

      {phase === 'error' ? (
        <>
          <p style={{ margin: '8px 0 8px', fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
            Could not start the reset. {error?.message || error?.detail}
          </p>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Button variant="quiet" onClick={run}>Try again</Button>
            <Button variant="quiet" onClick={() => setPhase('idle')}>Close</Button>
          </div>
        </>
      ) : null}
    </section>
  )
}
