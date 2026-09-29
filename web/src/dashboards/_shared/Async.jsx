import { isUnreachable } from '@/api.js'
import { Button, Panel } from './ui.jsx'

/**
 * Renders an async surface honestly (design plan §12.5): loading is *purposeful*
 * — it names the steps it is doing, never a bare spinner — error carries the real
 * message plus a retry, and empty states speak plainly and point at the next act.
 *
 * Pass `steps` (array of short strings) to narrate the loading state; pass
 * `empty` (a check on data) + `emptyNode` for the meaningful empty state.
 */
export function Async({ state, steps, activeStep = 0, empty, emptyNode, children, onRetry }) {
  const { status, data, error } = state

  if (status === 'loading' || status === 'idle') {
    return <Loading steps={steps} activeStep={activeStep} />
  }
  if (status === 'error') {
    return <ErrorState error={error} onRetry={onRetry || state.retry} />
  }
  if (empty && empty(data)) {
    return emptyNode || <Empty>Nothing here yet.</Empty>
  }
  return children(data)
}

export function Loading({ steps, activeStep = 0, label = 'Working' }) {
  if (!steps || steps.length === 0) {
    // Even the minimal loader names what it waits on — never a naked spinner.
    return (
      <div className="lb-fade" style={{ color: 'var(--ink-muted)', fontSize: 13, display: 'flex', gap: 8, alignItems: 'center' }}>
        <span className="lb-sweep" aria-hidden style={{ width: 44, height: 3, borderRadius: 3, background: 'var(--hairline)' }} />
        {label}…
      </div>
    )
  }
  return (
    <ol className="lb-fade" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 10 }}>
      {steps.map((s, i) => {
        const done = i < activeStep
        const now = i === activeStep
        return (
          <li key={s} style={{ display: 'flex', alignItems: 'center', gap: 10, color: now ? 'var(--ink)' : done ? 'var(--ink-muted)' : 'var(--ink-faint)' }}>
            <span
              aria-hidden
              className={now ? 'lb-tick__mark' : ''}
              style={{
                width: 8, height: 8, borderRadius: '50%',
                background: done ? 'var(--struct-2)' : now ? 'var(--accent)' : 'transparent',
                border: `1px solid ${done ? 'var(--struct-2)' : now ? 'var(--accent)' : 'var(--hairline)'}`,
                animation: now ? 'lb-blink 1s ease-in-out infinite' : 'none',
              }}
            />
            <span style={{ fontSize: 13 }}>{s}</span>
          </li>
        )
      })}
    </ol>
  )
}

export function ErrorState({ error, onRetry }) {
  // The backend simply not running is the single most common failure; it gets
  // the exact hint the api layer carries, calm and actionable — not a red box.
  const unreachable = isUnreachable(error)
  const msg = (error && (error.message || error.detail)) || 'Something went wrong.'
  return (
    <Panel style={{ maxWidth: 560 }}>
      <div style={{ color: unreachable ? 'var(--ink)' : 'var(--alert)', fontFamily: 'var(--font-display)', fontWeight: 700, marginBottom: 6 }}>
        {unreachable ? 'Backend not reachable' : 'Could not complete that'}
      </div>
      <p style={{ margin: '0 0 12px', color: 'var(--ink-muted)', fontSize: 13, lineHeight: 1.5 }}>{msg}</p>
      {onRetry ? <Button onClick={onRetry}>Retry</Button> : null}
    </Panel>
  )
}

export function Empty({ children, action }) {
  return (
    <div
      style={{
        border: '1px dashed var(--hairline)',
        borderRadius: 'var(--radius)',
        padding: 'calc(var(--gap) * 2)',
        textAlign: 'center',
        color: 'var(--ink-muted)',
        fontSize: 14,
      }}
    >
      <p style={{ margin: 0, maxWidth: 360, marginInline: 'auto', lineHeight: 1.5 }}>{children}</p>
      {action ? <div style={{ marginTop: 'var(--gap)' }}>{action}</div> : null}
    </div>
  )
}
