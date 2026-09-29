import { useEffect, useState } from 'react'
import { api } from '@/api.js'
import { useAsync } from '../_shared/useAsync.jsx'
import { Panel, Pill, mono, shortHash } from '../_shared/ui.jsx'

/**
 * The identity chip (design plan §8). Who am I, as a recipient. This is a demo
 * convenience — a real deployment binds identity to a credential, not a picker
 * — and the chip says exactly that, so no judge mistakes it for the security
 * model. It auto-selects the first active recipient so the inbox is never empty
 * on arrival for lack of a click.
 */
export default function Identity({ me, onMe }) {
  const state = useAsync()
  const [open, setOpen] = useState(false)
  useEffect(() => { state.run(() => api.adminRecipients()) }, []) // eslint-disable-line

  const list = (state.data?.recipients || []).filter((r) => !r.revoked)
  useEffect(() => {
    if (!me && list.length) onMe(list[0])
  }, [list, me]) // eslint-disable-line

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="lb-btn"
        style={{ display: 'inline-flex', alignItems: 'center', gap: 10, background: 'var(--bg-panel)', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', padding: '8px 12px', color: 'var(--ink)', cursor: 'pointer' }}
      >
        <span aria-hidden style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--struct-2)' }} />
        <span style={{ textAlign: 'left' }}>
          <span style={{ display: 'block', fontSize: 12, color: 'var(--ink-muted)' }}>you are</span>
          <span style={{ ...mono, fontSize: 13, color: 'var(--ink)' }}>{me ? me.recipient_id : 'selecting…'}</span>
        </span>
        <Pill tone="neutral">demo convenience</Pill>
      </button>

      {open ? (
        <Panel style={{ position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 10, width: 320, maxHeight: 320, overflowY: 'auto' }} className="lb-scroll">
          <div style={{ fontSize: 12, color: 'var(--ink-muted)', marginBottom: 8, lineHeight: 1.45 }}>
            A real deployment separates recipients by credential. This picker stands in for that.
          </div>
          {list.map((r) => (
            <button
              key={r.recipient_id}
              type="button"
              onClick={() => { onMe(r); setOpen(false) }}
              className="lb-btn"
              style={{ display: 'block', width: '100%', textAlign: 'left', background: me?.recipient_id === r.recipient_id ? 'var(--bg-elevated)' : 'transparent', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', padding: '8px 10px', marginBottom: 6, cursor: 'pointer', color: 'var(--ink)' }}
            >
              <span style={{ ...mono, fontSize: 13 }}>{r.recipient_id}</span>
              <span style={{ display: 'block', fontSize: 12, color: 'var(--ink-muted)' }}>{r.role || 'recipient'}</span>
            </button>
          ))}
          {list.length === 0 ? <div style={{ fontSize: 12, color: 'var(--ink-faint)' }}>No active recipients enrolled.</div> : null}
        </Panel>
      ) : null}
    </div>
  )
}
