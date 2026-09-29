import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * The one async state machine every dashboard surface uses. It exists so no
 * screen ever renders a bare spinner or a raw thrown error: the states are
 * explicit (idle → loading → success | error) and `retry` re-runs the last call.
 *
 * `run(fn)` supersedes any in-flight call (later wins), so a fast re-poll or a
 * tab switch never lands a stale result over a newer one.
 */
export function useAsync(initial = 'idle') {
  const [state, setState] = useState({ status: initial, data: undefined, error: undefined })
  const seq = useRef(0)
  const last = useRef(null)
  const alive = useRef(true)
  // Re-arm on mount, not just disarm on unmount: StrictMode mounts→unmounts→
  // remounts, and without the re-arm `alive` stays false after the remount and
  // every run() silently drops its result, hanging the surface on "loading".
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  const run = useCallback((fn) => {
    last.current = fn
    const mine = ++seq.current
    setState((s) => ({ status: 'loading', data: s.data, error: undefined }))
    return Promise.resolve()
      .then(fn)
      .then((data) => {
        if (alive.current && mine === seq.current) setState({ status: 'success', data, error: undefined })
        return data
      })
      .catch((error) => {
        // An aborted request is the caller's own supersede — not a failure.
        if (error && error.name === 'AbortError') return
        if (alive.current && mine === seq.current) setState((s) => ({ status: 'error', data: s.data, error }))
        throw error
      })
  }, [])

  const retry = useCallback(() => {
    if (last.current) return run(last.current)
  }, [run])

  const reset = useCallback(() => {
    seq.current++
    setState({ status: initial, data: undefined, error: undefined })
  }, [initial])

  return { ...state, run, retry, reset, setState }
}
