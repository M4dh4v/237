import { useEffect, useMemo, useState } from 'react'
import { api } from '@/api.js'
import { useAsync } from './_shared/useAsync.jsx'
import { Async, Empty } from './_shared/Async.jsx'
import { Pill, mono, Workspace, Panel, ZoneLabel } from './_shared/ui.jsx'
import Identity from './suchi/Identity.jsx'
import OpenFlow from './suchi/OpenFlow.jsx'
import './dashboards.css'

/**
 * Sūchī — the register (design plan §8). The recipient's side: the documents
 * addressed to you, opened one at a time. Opening is the single consequential
 * act — it appends a ledger entry and releases an ephemeral key — so the inbox
 * stays quiet on the left and the reading surface on the right carries all the
 * weight: the gate ring, then the marked copy at full size, then the receipt
 * that is the same event as the ledger leaf.
 */
export default function Suchi() {
  const [me, setMe] = useState(null)
  const [openDoc, setOpenDoc] = useState(null)

  return (
    <Workspace max={2400} style={{ height: 'calc(100dvh - var(--strip-h))', display: 'flex', flexDirection: 'column', padding: 'var(--gap)' }}>
      <Panel pad={0} style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'stretch', overflow: 'hidden' }}>
        <div style={{ width: 340, flex: '0 0 340px', borderRight: '1px solid var(--hairline)', padding: 'calc(var(--gap) * 1.5)', display: 'flex', flexDirection: 'column', gap: 'calc(var(--gap) * 1.5)', minHeight: 0 }}>
          <Identity me={me} onMe={(r) => { setMe(r); setOpenDoc(null) }} />
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }} className="lb-scroll">
            <Inbox me={me} openDoc={openDoc} onOpen={setOpenDoc} />
          </div>
        </div>

        <main style={{ flex: 1, minWidth: 0, padding: 'calc(var(--gap) * 2)', overflow: 'auto' }} className="lb-scroll">
          {me && openDoc ? (
            <OpenFlow key={openDoc.doc_id} me={me} doc={openDoc} />
          ) : (
            <div style={{ height: '100%', minHeight: 320, display: 'grid', placeItems: 'center', textAlign: 'center' }}>
              <div style={{ color: 'var(--ink-faint)', fontSize: 14, maxWidth: 360, lineHeight: 1.5 }}>
                {me
                  ? 'Choose a document on the left. Opening it is the act that writes the ledger — nothing is recorded until you do.'
                  : 'Select who you are to see the documents addressed to you.'}
              </div>
            </div>
          )}
        </main>
      </Panel>
    </Workspace>
  )
}

/**
 * The inbox: documents this recipient has a grant on. Polls quietly so a fresh
 * distribution shows up without a reload; new rows rise in. State is honest —
 * "granted" (can open) vs "opened" (already appended a leaf) vs "revoked".
 */
function Inbox({ me, openDoc, onOpen }) {
  const state = useAsync()
  const load = () => state.run(() => api.documents())
  useEffect(() => {
    if (!me) return
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [me]) // eslint-disable-line

  const mine = useMemo(() => {
    const docs = state.data?.documents || []
    if (!me) return []
    return docs.filter((d) => d.sealed && (d.recipients || []).includes(me.recipient_id))
  }, [state.data, me])

  if (!me) {
    return <div style={{ color: 'var(--ink-faint)', fontSize: 13 }}>No identity selected.</div>
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 'var(--gap)' }}>
        <ZoneLabel>addressed to you</ZoneLabel>
        <span style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)' }}>{mine.length}</span>
      </div>
      <Async
        state={state}
        steps={['reading the sealed corpus', 'matching your grants']}
        activeStep={1}
        empty={() => mine.length === 0}
        emptyNode={<Empty>Nothing addressed to you yet. A sender seals a copy to you from the gate.</Empty>}
        onRetry={load}
      >
        {() => (
          <div style={{ display: 'grid', gap: 8 }}>
            {mine.map((d) => {
              const on = openDoc?.doc_id === d.doc_id
              return (
                <button
                  key={d.doc_id}
                  type="button"
                  className={`lb-card lb-rise ${on ? 'lb-card--on' : ''}`}
                  onClick={() => onOpen(d)}
                  style={{ textAlign: 'left', background: 'var(--bg-panel)', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', padding: '12px', cursor: 'pointer', color: 'var(--ink)' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
                    <span style={{ ...mono, fontSize: 13 }}>{d.doc_id}</span>
                    <Pill tone="neutral">sealed</Pill>
                  </div>
                  <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--ink-muted)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{d.preview}</p>
                  <div style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)', marginTop: 6 }}>{d.words} words · {d.recipients.length} recipient(s)</div>
                </button>
              )
            })}
          </div>
        )}
      </Async>
    </div>
  )
}
