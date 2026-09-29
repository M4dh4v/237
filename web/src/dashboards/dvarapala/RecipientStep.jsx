import { useEffect, useState } from 'react'
import { api } from '@/api.js'
import { useAsync } from '../_shared/useAsync.jsx'
import { Async, ErrorState, Empty, Loading } from '../_shared/Async.jsx'
import { Button, Field, Input, Panel, Pill, mono, shortHash } from '../_shared/ui.jsx'

/**
 * Step 2 — recipients (design plan §7.2). Who is inside this distribution. The
 * same file goes to everyone; each copy quietly carries a different mark, so the
 * list here is the set of people the ledger will later be able to tell apart.
 * Revoked recipients are shown but not selectable — honest about who *can* open.
 */
export default function RecipientStep({ selected, onSelected, onNext, onBack }) {
  const list = useAsync()
  const load = () => list.run(() => api.adminRecipients())
  useEffect(() => { load() }, []) // eslint-disable-line

  const chosen = selected || []
  const toggle = (id) =>
    onSelected(chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id])

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 'var(--gap)' }}>
        <div>
          <h3 style={{ fontSize: 20 }}>Choose who is included</h3>
          <p style={{ color: 'var(--ink-muted)', margin: '6px 0 0', maxWidth: 560, lineHeight: 1.5 }}>
            Everyone receives the same file. Each copy carries a different mark, so a leaked copy
            can be traced back to exactly one of these recipients.
          </p>
        </div>
        <Pill tone={chosen.length ? 'accent' : 'neutral'}>{chosen.length} selected</Pill>
      </div>

      <div style={{ marginTop: 'var(--gap)', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,300px)', gap: 'calc(var(--gap) * 1.5)', alignItems: 'start' }}>
        <Async
          state={list}
          steps={['reading enrolled recipients', 'checking certificates']}
          activeStep={1}
          empty={(d) => !d?.recipients?.length}
          emptyNode={<Empty>No recipients enrolled yet. Add one on the right.</Empty>}
          onRetry={load}
        >
          {(d) => (
            <div className="lb-scroll" style={{ display: 'grid', gap: 8, maxHeight: 440, overflowY: 'auto', paddingRight: 4 }}>
              {d.recipients.map((r) => {
                const on = chosen.includes(r.recipient_id)
                const revoked = r.revoked
                return (
                  <button
                    key={r.recipient_id}
                    type="button"
                    disabled={revoked}
                    className={`lb-card ${on ? 'lb-card--on' : ''}`}
                    onClick={() => !revoked && toggle(r.recipient_id)}
                    style={{
                      textAlign: 'left', background: 'var(--bg-panel)', border: '1px solid var(--hairline)',
                      borderRadius: 'var(--radius)', padding: '12px', cursor: revoked ? 'not-allowed' : 'pointer',
                      color: 'var(--ink)', opacity: revoked ? 0.55 : 1,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
                      <span style={{ ...mono, fontSize: 13, color: 'var(--ink)' }}>{r.recipient_id}</span>
                      {revoked ? <Pill tone="alert">revoked</Pill> : on ? <Pill tone="accent">included</Pill> : null}
                    </div>
                    <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 12, color: 'var(--ink-muted)' }}>
                      <span>{r.role || 'recipient'}</span>
                      {r.serial ? <span style={{ ...mono, color: 'var(--ink-faint)' }}>cert {shortHash(String(r.serial), 6, 4)}</span> : null}
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </Async>

        <AddRecipient onAdded={(r) => { load().then(() => onSelected([...chosen, r.recipientId])) }} />
      </div>

      <StepFooter onBack={onBack} onNext={onNext} nextLabel="Set classification →" nextDisabled={!chosen.length} />
    </div>
  )
}

function AddRecipient({ onAdded }) {
  const [displayName, setName] = useState('')
  const [role, setRole] = useState('')
  const [open, setOpen] = useState(false)
  const submit = useAsync()
  const go = () =>
    submit.run(() => api.createRecipient({ displayName, role })).then((r) => {
      onAdded(r); setName(''); setRole(''); setOpen(false)
    }).catch(() => {})

  return (
    <Panel style={{ position: 'sticky', top: 'var(--gap)' }}>
      <div style={{ fontFamily: 'var(--font-display)', fontWeight: 500, color: 'var(--ink)', marginBottom: 4 }}>Enroll a recipient</div>
      <p style={{ margin: '0 0 var(--gap)', fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.45 }}>
        The authority generates a post-quantum keypair for the new officer. No key material touches this browser.
      </p>
      {!open ? (
        <Button onClick={() => setOpen(true)}>+ New recipient</Button>
      ) : submit.status === 'loading' ? (
        <Loading steps={['generating PQC keypair', 'signing the certificate']} activeStep={0} />
      ) : (
        <div style={{ display: 'grid', gap: 'var(--gap)' }}>
          <Field label="Display name"><Input value={displayName} onChange={(e) => setName(e.target.value)} placeholder="e.g. Lt. Cdr. Rao" /></Field>
          <Field label="Role"><Input value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. wardroom" /></Field>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="primary" disabled={!displayName.trim()} onClick={go}>Enroll</Button>
            <Button variant="quiet" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </div>
      )}
      {submit.status === 'error' ? <div style={{ marginTop: 'var(--gap)' }}><ErrorState error={submit.error} onRetry={submit.retry} /></div> : null}
    </Panel>
  )
}

export function StepFooter({ onBack, onNext, nextLabel, nextDisabled }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 'calc(var(--gap) * 1.5)', paddingTop: 'var(--gap)', borderTop: '1px solid var(--hairline)' }}>
      {onBack ? <Button variant="quiet" onClick={onBack}>← Back</Button> : <span />}
      {onNext ? <Button variant="primary" disabled={nextDisabled} onClick={onNext}>{nextLabel}</Button> : <span />}
    </div>
  )
}
