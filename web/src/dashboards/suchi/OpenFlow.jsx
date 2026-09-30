import { useState } from 'react'
import { api, isFailClosed } from '@/api.js'
import { WitnessRing, FailClosed, PresentNotVerified, Caveat, ClassificationBanner } from '@/components'
import { useAsync } from '../_shared/useAsync.jsx'
import { Loading, ErrorState } from '../_shared/Async.jsx'
import { Button, Panel, Pill, mono, shortHash } from '../_shared/ui.jsx'
import { CertificateLauncher } from '../Pramanapatra.jsx'

/**
 * The open surface (design plan §8.2). Opening is the one consequential act:
 * it appends a ledger leaf and releases an ephemeral key, so before it we show
 * exactly that ("nothing is recorded until you open"), and after it we show the
 * receipt and the ledger entry as the SAME event. Fail-closed is a held
 * guarantee, not an error. The copy you receive is uniquely marked — the reader
 * makes that visible rather than asserted.
 */
export default function OpenFlow({ me, doc }) {
  const open = useAsync()
  const act = () =>
    open.run(() => api.open({ doc_id: doc.doc_id, recipient_id: me.recipient_id, mark: true })).catch(() => {})

  const failClosed = open.status === 'error' && isFailClosed(open.error)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 'var(--gap)', marginBottom: 'var(--gap)' }}>
        <div>
          <h3 style={{ fontSize: 20 }}>{doc.doc_id}</h3>
          <div style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)' }}>addressed to {me.recipient_id}</div>
        </div>
        {open.status === 'success' ? <Pill tone="struct">opened</Pill> : <Pill tone="neutral">sealed</Pill>}
      </div>

      {open.status === 'success' ? (
        <Opened data={open.data} doc={doc} />
      ) : failClosed ? (
        <div style={{ display: 'grid', gap: 'var(--gap)' }}>
          <FailClosed reason={open.error} />
          <div><Button onClick={act}>Try opening again</Button></div>
        </div>
      ) : open.status === 'error' ? (
        <ErrorState error={open.error} onRetry={open.retry} />
      ) : open.status === 'loading' ? (
        <Panel><Loading steps={['requesting the ephemeral key', 'appending the ledger leaf', 'marking your copy']} activeStep={1} /></Panel>
      ) : (
        <Panel style={{ display: 'grid', gap: 'var(--gap)', placeItems: 'center', textAlign: 'center', padding: 'calc(var(--gap) * 2)' }}>
          <WitnessRing scale="widget" data={{ witnesses: 3 }} />
          <p style={{ margin: 0, color: 'var(--ink-muted)', fontSize: 14, lineHeight: 1.55, maxWidth: 420 }}>
            This copy is sealed to the authority, not to you — opening it asks the authority for a
            one-time key and, in the same step, writes an entry to the witnessed ledger.
            <strong style={{ color: 'var(--ink)', fontWeight: 500 }}> Nothing is recorded until you open.</strong>
          </p>
          <Button variant="primary" onClick={act}>Open — and record it</Button>
        </Panel>
      )}
    </div>
  )
}

function Opened({ data, doc }) {
  const [showMark, setShowMark] = useState(false)
  const marked = data.marked_text || data.plaintext || ''
  const plain = data.plaintext || ''
  const diff = data.mark_diff || []
  const entry = data.ledger_entry || {}
  const [copied, setCopied] = useState(false)

  // Format-aware original. Lane C flag: api.open() returns the marked text only —
  // when it also returns the original bytes (image_data_url / pdf_data_url), the
  // viewer lights up automatically. Until then we render the marked text page.
  const image = data.image_data_url
  const pdf = data.pdf_data_url
  const kind = image ? 'image' : pdf ? 'pdf' : 'text'

  const copy = () => {
    navigator.clipboard?.writeText(marked).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }).catch(() => {})
  }

  return (
    <div className="lb-fade" style={{ display: 'grid', gap: 'calc(var(--gap) * 1.25)' }}>
      {/* The received copy, at full size — the whole point of this screen. */}
      <div style={{ border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', overflow: 'hidden', background: 'var(--bg)' }}>
        <ClassificationBanner level={doc.classification || 'UNCLASSIFIED'} position="top" />
        <div style={{ display: 'flex', gap: 8, padding: '10px 14px', borderBottom: '1px solid var(--hairline)', alignItems: 'center' }} className="lb-noprint">
          <span style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>your copy · {kind}</span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            {kind === 'text' ? (
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--ink-muted)', cursor: 'pointer' }}>
                <input type="checkbox" checked={showMark} onChange={(e) => setShowMark(e.target.checked)} />
                reveal the mark ({diff.length})
              </label>
            ) : null}
            <Button variant="quiet" onClick={copy}>{copied ? 'copied ✓' : 'Copy'}</Button>
            <Button variant="quiet" onClick={() => window.print()}>Screenshot / print</Button>
          </div>
        </div>
        <DocumentView kind={kind} image={image} pdf={pdf} marked={marked} plain={plain} diff={diff} showMark={showMark} />
      </div>

      {/* The receipt — a slim strip, because your open IS the ledger leaf. */}
      <div className="lb-noprint" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--gap)', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', background: 'var(--bg-panel)', padding: 'var(--gap) calc(var(--gap) * 1.25)' }}>
        <div style={{ ...mono, fontSize: 11, color: 'var(--ink-muted)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>ledger leaf</div>
        <KV k="index" v={entry.index != null ? `#${entry.index}` : '—'} />
        <KV k="leaf hash" v={shortHash(entry.leaf_hash, 12, 8)} mono />
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 'var(--gap)' }}>
          <PresentNotVerified />
          {entry.index != null ? <CertificateLauncher findingId={entry.index} /> : null}
        </div>
      </div>

      <div className="lb-noprint" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--gap)', alignItems: 'center' }}>
        <Caveat kind="proves-key" />
        {data.caveat ? <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5, flex: 1, minWidth: 200 }}>{data.caveat}</p> : null}
      </div>
    </div>
  )
}

/** The reading surface, sized to fill the stage. Format-aware: an image renders
 * as an image, a PDF in the browser's own viewer, text as a readable column. */
function DocumentView({ kind, image, pdf, marked, plain, diff, showMark }) {
  if (kind === 'image') {
    return (
      <div style={{ display: 'grid', placeItems: 'center', padding: 'calc(var(--gap) * 1.5)', background: 'var(--bg)' }}>
        <img src={image} alt="your marked copy" style={{ maxWidth: '100%', height: 'auto', borderRadius: 2 }} />
      </div>
    )
  }
  if (kind === 'pdf') {
    return <iframe src={pdf} title="your marked copy" style={{ width: '100%', height: '68vh', border: 'none', background: 'var(--bg)' }} />
  }
  return (
    <div className="lb-scroll" style={{ minHeight: '52vh', maxHeight: '68vh', overflowY: 'auto', padding: 'calc(var(--gap) * 2)', fontSize: 15, lineHeight: 1.8, color: 'var(--ink)', whiteSpace: 'pre-wrap', maxWidth: 760, margin: '0 auto' }}>
      {showMark ? <MarkedText plain={plain} diff={diff} /> : marked}
    </div>
  )
}

/** Render the plaintext, highlighting the words the mark substituted. */
function MarkedText({ plain, diff }) {
  const byPos = new Map(diff.map((d) => [d.position, d]))
  const words = plain.split(/(\s+)/)
  let wi = -1
  return (
    <span>
      {words.map((w, i) => {
        if (/^\s+$/.test(w)) return w
        wi += 1
        const hit = byPos.get(wi)
        if (!hit) return <span key={i}>{w}</span>
        return (
          <mark key={i} title={`was “${hit.original}”`} style={{ background: 'color-mix(in srgb, var(--accent) 22%, transparent)', color: 'var(--ink)', borderRadius: 2, padding: '0 1px' }}>
            {hit.marked || w}
          </mark>
        )
      })}
    </span>
  )
}

function KV({ k, v, mono: isMono }) {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'baseline', gap: 8, fontSize: 13 }}>
      <span style={{ color: 'var(--ink-muted)' }}>{k}</span>
      <span style={isMono ? mono : undefined}>{v}</span>
    </div>
  )
}
