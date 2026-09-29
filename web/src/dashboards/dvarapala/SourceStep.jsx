import { useEffect, useRef, useState } from 'react'
import { api } from '@/api.js'
import { useAsync } from '../_shared/useAsync.jsx'
import { Async, Loading, ErrorState, Empty } from '../_shared/Async.jsx'
import { Button, Field, Input, Panel, Tabs, Textarea, mono, shortHash } from '../_shared/ui.jsx'
import CapacityMeter from './CapacityMeter.jsx'

/**
 * Step 1 — the source (design plan §7.1). One inviting panel, four quiet ways in:
 * upload any file, compose in-app, the curated corpus (first-class, always-works
 * demo path), or a fast paste. Whatever the mode, the outcome is identical
 * downstream: a document body enters the pipeline. The preview + capacity meter
 * live on the right so the sender sees what they are about to seal.
 */
const TABS = [
  { id: 'corpus', label: 'Curated corpus' },
  { id: 'upload', label: 'Upload a file' },
  { id: 'compose', label: 'Compose' },
  { id: 'paste', label: 'Paste text' },
]

export default function SourceStep({ source, onSource, onNext }) {
  const [tab, setTab] = useState('corpus')
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0, 380px)', gap: 'calc(var(--gap) * 1.5)' }}>
      <div>
        <SectionHead
          title="Choose what to seal"
          sub="Drop a file, pick from the corpus, or write one here. Every path becomes the same sealable document body."
        />
        <div style={{ marginTop: 'var(--gap)' }}>
          <Tabs tabs={TABS} active={tab} onChange={setTab} />
          <div style={{ paddingTop: 'var(--gap)' }}>
            {tab === 'corpus' && <CorpusPicker source={source} onSource={onSource} />}
            {tab === 'upload' && <UploadDrop onSource={onSource} />}
            {tab === 'compose' && <Compose onSource={onSource} />}
            {tab === 'paste' && <PasteText onSource={onSource} />}
          </div>
        </div>
      </div>

      <PreviewPane source={source} tab={tab} onNext={onNext} />
    </div>
  )
}

function SectionHead({ title, sub }) {
  return (
    <div>
      <h3 style={{ fontSize: 20 }}>{title}</h3>
      {sub ? <p style={{ color: 'var(--ink-muted)', margin: '6px 0 0', maxWidth: 560, lineHeight: 1.5 }}>{sub}</p> : null}
    </div>
  )
}

function CorpusPicker({ source, onSource }) {
  const state = useAsync()
  useEffect(() => { state.run(() => api.documents()) }, []) // eslint-disable-line

  return (
    <Async
      state={state}
      steps={['reading the sealed corpus', 'measuring each document']}
      activeStep={1}
      empty={(d) => !d?.documents?.length}
      emptyNode={<Empty>No corpus documents yet. Upload or compose one instead.</Empty>}
    >
      {(d) => (
        <div className="lb-scroll" style={{ display: 'grid', gap: 8, maxHeight: 420, overflowY: 'auto', paddingRight: 4 }}>
          {d.documents.map((doc) => {
            const on = source?.docId === doc.doc_id
            return (
              <button
                key={doc.doc_id}
                type="button"
                className={`lb-card ${on ? 'lb-card--on' : ''}`}
                onClick={() =>
                  onSource({
                    docId: doc.doc_id,
                    title: doc.doc_id,
                    preview: doc.preview,
                    origin: 'corpus',
                    capacity: { positions: doc.tardos_positions, needed: doc.tardos_required, strength: doc.guarantee },
                  })
                }
                style={cardStyle}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <span style={{ ...mono, color: 'var(--ink)', fontSize: 13 }}>{doc.doc_id}</span>
                  <span style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)' }}>{doc.words} words</span>
                </div>
                <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--ink-muted)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                  {doc.preview}
                </p>
              </button>
            )
          })}
        </div>
      )}
    </Async>
  )
}

function UploadDrop({ onSource }) {
  const submit = useAsync()
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef(null)

  const ingest = (file) => {
    if (!file) return
    submit
      .run(() => api.uploadSource(file))
      .then((res) => onSource({ ...res, title: file.name, origin: 'upload' }))
      .catch(() => {})
  }

  if (submit.status === 'loading') {
    return <Panel><Loading steps={['reading the file', 'extracting the text layer', 'measuring watermark capacity']} activeStep={1} /></Panel>
  }
  if (submit.status === 'error') return <ErrorState error={submit.error} onRetry={submit.retry} />

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); ingest(e.dataTransfer.files?.[0]) }}
      style={{
        border: `1px dashed ${dragging ? 'var(--accent)' : 'var(--hairline)'}`,
        borderRadius: 'var(--radius)',
        background: dragging ? 'color-mix(in srgb, var(--accent) 6%, var(--bg-panel))' : 'var(--bg-panel)',
        padding: 'calc(var(--gap) * 2)',
        textAlign: 'center',
        transition: 'border-color var(--dur-fast), background var(--dur-fast)',
      }}
    >
      <p style={{ margin: 0, color: 'var(--ink)', fontFamily: 'var(--font-display)', fontWeight: 500 }}>Drop a file, or start one here.</p>
      <p style={{ margin: '6px 0 var(--gap)', color: 'var(--ink-muted)', fontSize: 13 }}>PDF, image (PNG/JPG), or text / markdown.</p>
      <Button onClick={() => inputRef.current?.click()}>Browse files</Button>
      <input ref={inputRef} type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.txt,.md,image/*,text/*" onChange={(e) => ingest(e.target.files?.[0])} />
      <p style={{ margin: 'var(--gap) 0 0', fontSize: 12, color: 'var(--ink-faint)', lineHeight: 1.45 }}>
        Uploaded files become the document body; the mark rides in the text layer, so text-bearing documents trace best.
      </p>
    </div>
  )
}

function Compose({ onSource }) {
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const submit = useAsync()
  const go = () => submit.run(() => api.composeSource({ title, body })).then((res) => onSource({ ...res, title: title || 'Untitled memo', origin: 'compose' })).catch(() => {})
  return (
    <div style={{ display: 'grid', gap: 'var(--gap)' }}>
      <Field label="Title"><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Fleet Movement Order 14" /></Field>
      <Field label="Body" hint="Longer text carries a stronger, formally-bounded mark.">
        <Textarea rows={8} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Type or paste the memo…" />
      </Field>
      <div>
        <Button variant="primary" disabled={!body.trim() || submit.status === 'loading'} onClick={go}>
          {submit.status === 'loading' ? 'Registering…' : 'Use this document'}
        </Button>
      </div>
      {submit.status === 'error' ? <ErrorState error={submit.error} onRetry={submit.retry} /> : null}
    </div>
  )
}

function PasteText({ onSource }) {
  const [body, setBody] = useState('')
  const submit = useAsync()
  const go = () => submit.run(() => api.composeSource({ title: 'Pasted document', body })).then((res) => onSource({ ...res, title: 'Pasted document', origin: 'paste' })).catch(() => {})
  return (
    <div style={{ display: 'grid', gap: 'var(--gap)' }}>
      <Field label="Paste a document body">
        <Textarea rows={10} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Paste text to seal…" />
      </Field>
      <div>
        <Button variant="primary" disabled={!body.trim() || submit.status === 'loading'} onClick={go}>
          {submit.status === 'loading' ? 'Registering…' : 'Use this text'}
        </Button>
      </div>
      {submit.status === 'error' ? <ErrorState error={submit.error} onRetry={submit.retry} /> : null}
    </div>
  )
}

function PreviewPane({ source, tab, onNext }) {
  return (
    <Panel style={{ position: 'sticky', top: 'var(--gap)', alignSelf: 'start' }}>
      <div style={{ fontSize: 12, color: 'var(--ink-muted)', marginBottom: 'var(--gap)', letterSpacing: '0.04em', textTransform: 'uppercase', ...mono }}>preview</div>
      {!source ? (
        <div style={{ color: 'var(--ink-faint)', fontSize: 13, lineHeight: 1.5 }}>
          Nothing chosen yet. Pick a source on the left and it appears here with its watermark capacity.
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 'var(--gap)' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 500, color: 'var(--ink)' }}>{source.title}</div>
            <div style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)', marginTop: 2 }}>id {shortHash(source.docId, 10, 4)}</div>
          </div>
          <div
            className="lb-scroll"
            style={{
              maxHeight: 200, overflowY: 'auto', padding: '10px 12px',
              background: 'var(--bg)', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)',
              fontSize: 13, color: 'var(--ink-muted)', lineHeight: 1.55, whiteSpace: 'pre-wrap',
            }}
          >
            {source.preview || '(no preview)'}
          </div>
          <CapacityMeter capacity={source.capacity} showCaveat={source.origin === 'upload'} />
          <Button variant="primary" onClick={onNext} style={{ width: '100%', justifyContent: 'center' }}>
            Choose recipients →
          </Button>
        </div>
      )}
    </Panel>
  )
}

const cardStyle = {
  textAlign: 'left',
  background: 'var(--bg-panel)',
  border: '1px solid var(--hairline)',
  borderRadius: 'var(--radius)',
  padding: '12px',
  cursor: 'pointer',
  color: 'var(--ink)',
}
