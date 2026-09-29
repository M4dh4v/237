import { useState } from 'react'
import { api } from '@/api.js'
import { WitnessRing, PresentNotVerified, Caveat, ClassificationBanner } from '@/components'
import { useAsync } from './_shared/useAsync.jsx'
import { Loading, ErrorState } from './_shared/Async.jsx'
import { Button, Field, Input, Panel, mono, shortHash } from './_shared/ui.jsx'
import './dashboards.css'

/**
 * Pramāṇapatra — the certificate of proof (design plan §11). Pulled from any
 * finding: a ledger entry index (an open event, or the leaf a trace pointed at).
 *
 * The load-bearing artefact is the JSON evidence bundle, checkable by the
 * standalone verifier/. This screen renders the human-readable face of it and
 * lets you export both — but it never claims to have *verified* anything itself
 * (sakshya-honesty §1). It presents what the bundle contains and says, in the
 * PresentNotVerified strip, exactly who does the verifying. The wax seal is a
 * seal, not a checkmark.
 */
export default function Pramanapatra() {
  const cert = useAsync()
  const [id, setId] = useState('')

  const build = () => {
    const n = id.trim()
    if (n === '') return
    cert.run(() => api.certificate(n)).catch(() => {})
  }

  return (
    <div style={{ padding: 'calc(var(--gap) * 1.5)', display: 'grid', gap: 'calc(var(--gap) * 1.5)' }}>
      <div>
        <h2 style={{ fontSize: 24, fontFamily: 'var(--font-display)' }}>Pramāṇapatra</h2>
        <p style={{ color: 'var(--ink-muted)', margin: '4px 0 0', maxWidth: 620, lineHeight: 1.5 }}>
          The evidence bundle for one finding, as a certificate. The JSON below is what an independent
          verifier checks — this page renders its human face and does not itself sit in judgement.
        </p>
      </div>

      <Panel style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 'var(--gap)', alignItems: 'end' }}>
        <Field label="Finding — the ledger entry index it rests on">
          <Input value={id} onChange={(e) => setId(e.target.value)} placeholder="e.g. 3" inputMode="numeric" onKeyDown={(e) => e.key === 'Enter' && build()} />
        </Field>
        <Button variant="primary" disabled={!id.trim()} onClick={build}>Draw up the certificate</Button>
      </Panel>

      {cert.status === 'loading' ? (
        <Panel><Loading steps={['gathering the ledger entry', 'chaining it to the witnessed head', 'collecting witness co-signatures', 'sealing the bundle']} activeStep={2} /></Panel>
      ) : cert.status === 'error' ? (
        <ErrorState error={cert.error} onRetry={cert.retry} />
      ) : cert.status === 'success' ? (
        <Certificate bundle={cert.data?.json} note={cert.data?.note} />
      ) : (
        <Panel style={{ color: 'var(--ink-faint)', fontSize: 14, lineHeight: 1.55, maxWidth: 560 }}>
          In the live flow this is launched straight from an open receipt or a trace result — the finding
          id is carried in. Here, name the ledger entry you want certified.
        </Panel>
      )}
    </div>
  )
}

function Certificate({ bundle, note }) {
  if (!bundle || !Array.isArray(bundle.entries) || bundle.entries.length === 0) {
    return <Inconclusive note={note} />
  }
  const entry = bundle.entries[0]
  const req = entry.leaf?.request || {}
  const head = bundle.head || {}

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `pramanapatra-${entry.index}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={{ border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
      <ClassificationBanner level={req.classification || 'UNCLASSIFIED'} position="top" />

      <div style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0,1fr)', gap: 'calc(var(--gap) * 1.5)', padding: 'calc(var(--gap) * 1.5)', alignItems: 'center' }}>
        <div style={{ display: 'grid', placeItems: 'center', gap: 8 }}>
          <WitnessRing scale="widget" data={{ witnesses: Object.keys(bundle.witness_pubs || {}).length || 3 }} highlightLeaf={entry.index} />
          <span style={{ ...mono, fontSize: 10, color: 'var(--ink-faint)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>witnessed seal</span>
        </div>
        <div>
          <div style={{ ...mono, fontSize: 11, color: 'var(--ink-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>this certificate attests</div>
          <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6, color: 'var(--ink)' }}>
            The ledger holds an entry, at index <strong style={{ ...mono }}>#{entry.index}</strong>, recording that
            recipient <strong style={{ ...mono }}>{req.recipient_id || entry.recipient_id || '—'}</strong> opened
            document <strong style={{ ...mono }}>{req.doc_id || '—'}</strong>
            {req.timestamp ? <> at <span style={{ ...mono }}>{req.timestamp}</span></> : null}.
          </p>
          <p style={{ margin: '10px 0 0', fontSize: 13, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
            This is a statement the recipient's own key signed — not a claim by the authority. What it proves,
            and what it does not, is set out below.
          </p>
        </div>
      </div>

      <div className="lb-noprint" style={{ display: 'flex', gap: 8, padding: '10px calc(var(--gap) * 1.5)', borderTop: '1px solid var(--hairline)', borderBottom: '1px solid var(--hairline)' }}>
        <Button variant="primary" onClick={downloadJson}>Download the JSON bundle</Button>
        <Button variant="quiet" onClick={() => window.print()}>Print / save as PDF</Button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,340px)', gap: 'calc(var(--gap) * 1.5)', padding: 'calc(var(--gap) * 1.5)', alignItems: 'start' }}>
        <div style={{ display: 'grid', gap: 'var(--gap)' }}>
          <Contents entry={entry} head={head} bundle={bundle} />
          <Caveat kind="proves-key" />
        </div>
        <div style={{ display: 'grid', gap: 'var(--gap)' }} className="lb-noprint">
          <PresentNotVerified />
          {note ? <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5 }}>{note}</p> : null}
        </div>
      </div>
    </div>
  )
}

/** What the bundle carries for the verifier to re-derive — listed, not asserted true. */
function Contents({ entry, head, bundle }) {
  const items = [
    ['inclusion proof', `${(entry.inclusion_proof || []).length} hashes to the head`],
    ['consistency to head', entry.consistency_to_head ? 'present' : '—'],
    ['witnessed head size', head.tree_size != null ? `${head.tree_size} leaves` : '—'],
    ['witness co-signatures', `${Object.keys(bundle.witness_pubs || {}).length} known, quorum ${bundle.witness_quorum ?? '—'}`],
    ['recipient certificate', entry.recipient_cert ? 'CA-signed, enclosed' : '—'],
    ['recipient key', shortHash(entry.recipient_pub, 10, 6)],
  ]
  return (
    <Panel>
      <div style={{ ...mono, fontSize: 11, color: 'var(--ink-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>what the bundle carries</div>
      <div style={{ display: 'grid', gap: 4 }}>
        {items.map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, padding: '3px 0' }}>
            <span style={{ color: 'var(--ink-muted)' }}>{k}</span>
            <span style={{ ...mono, fontSize: 12, textAlign: 'right' }}>{v}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function Inconclusive({ note }) {
  return (
    <Panel style={{ display: 'grid', gap: 'var(--gap)' }}>
      <div style={{ ...mono, fontSize: 11, color: 'var(--accent-soft)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>inconclusive</div>
      <p style={{ margin: 0, fontSize: 14, color: 'var(--ink)', lineHeight: 1.6, maxWidth: 560 }}>
        No entry could be assembled into a certificate for that finding. That is a truthful outcome, not an
        error to paper over: without a committed ledger entry there is nothing for a verifier to check, and
        so nothing this page will dress up as proof.
      </p>
      {note ? <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5 }}>{note}</p> : null}
    </Panel>
  )
}
