import { useRef, useState } from 'react'
import { api } from '@/api.js'
import { useAsync } from './_shared/useAsync.jsx'
import { Loading, ErrorState } from './_shared/Async.jsx'
import { Button, Field, Panel, Tabs, Textarea, mono } from './_shared/ui.jsx'
import Findings from './anvesana/Findings.jsx'
import './dashboards.css'

/**
 * Anveṣaṇa — the investigation (design plan §9). A leaked artefact goes in; the
 * pipeline says which document it is and, separately, which recipient's copy it
 * was. The two are never merged into one score (sakshya-honesty §5): a strong
 * document match with a weak attribution is a real and common state, and hiding
 * it behind one number would be a lie. The intake offers three honest ways in;
 * the pipeline names each step it runs rather than spinning.
 */
const MODES = [
  { id: 'upload', label: 'Upload a leaked file' },
  { id: 'example', label: 'Try a built-in example' },
  { id: 'paste', label: 'Paste suspect text' },
]

export default function Anvesana() {
  const [mode, setMode] = useState('example')
  const run = useAsync()

  return (
    <div style={{ padding: 'calc(var(--gap) * 1.5)', display: 'grid', gap: 'calc(var(--gap) * 1.5)' }}>
      <div>
        <h2 style={{ fontSize: 24, fontFamily: 'var(--font-display)' }}>Anveṣaṇa</h2>
        <p style={{ color: 'var(--ink-muted)', margin: '4px 0 0', maxWidth: 620, lineHeight: 1.5 }}>
          Trace a leaked copy. The pipeline reports two separate things — which document, and whose
          copy — and never collapses them into a single verdict.
        </p>
      </div>

      <Panel>
        <Tabs tabs={MODES} active={mode} onChange={setMode} />
        <div style={{ paddingTop: 'var(--gap)' }}>
          {mode === 'upload' && <UploadIntake run={run} />}
          {mode === 'example' && <ExampleIntake run={run} />}
          {mode === 'paste' && <PasteIntake run={run} />}
        </div>
      </Panel>

      {run.status === 'loading' ? (
        <Panel><Loading steps={['extracting the leaked text', 'aligning against the sealed corpus', 'recovering the watermark', 'ranking likely recipients']} activeStep={2} /></Panel>
      ) : run.status === 'error' ? (
        <ErrorState error={run.error} onRetry={run.retry} />
      ) : run.status === 'success' ? (
        <Findings result={run.data} />
      ) : null}
    </div>
  )
}

function UploadIntake({ run }) {
  const inputRef = useRef(null)
  const [name, setName] = useState('')
  const pick = (file) => { if (!file) return; setName(file.name); run.run(() => api.uploadLeak(file)).catch(() => {}) }
  return (
    <div>
      <p style={{ margin: '0 0 var(--gap)', color: 'var(--ink-muted)', fontSize: 13, lineHeight: 1.5 }}>
        A whole leaked document — PDF, image, or text. Each page is extracted (text layer, or OCR fallback) before the mark is read.
      </p>
      <Button variant="primary" onClick={() => inputRef.current?.click()}>Choose a leaked file</Button>
      {name ? <span style={{ ...mono, fontSize: 12, color: 'var(--ink-faint)', marginLeft: 10 }}>{name}</span> : null}
      <input ref={inputRef} type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.txt,.md,image/*,text/*" onChange={(e) => pick(e.target.files?.[0])} />
    </div>
  )
}

function ExampleIntake({ run }) {
  const KINDS = [
    { id: 'text', name: 'Leaked text', sub: 'a copied-out passage' },
    { id: 'screenshot', name: 'Screenshot', sub: 'a photographed page (OCR)' },
    { id: 'collusion', name: 'Collusion', sub: 'two recipients averaged their copies' },
  ]
  return (
    <div>
      <p style={{ margin: '0 0 var(--gap)', color: 'var(--ink-muted)', fontSize: 13, lineHeight: 1.5 }}>
        Ready-made artefacts that always work offline — including the hard case where two recipients combined their copies to blur the mark.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 8 }}>
        {KINDS.map((k) => (
          <button
            key={k.id}
            type="button"
            className="lb-card"
            onClick={() => run.run(() => api.example(k.id).then((ex) => api.leakcheck({ text: ex.leaked_text, image_b64: ex.image_b64 }))).catch(() => {})}
            style={{ textAlign: 'left', background: 'var(--bg-panel)', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', padding: '12px', cursor: 'pointer', color: 'var(--ink)' }}
          >
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 500 }}>{k.name}</div>
            <div style={{ fontSize: 12, color: 'var(--ink-muted)', marginTop: 4 }}>{k.sub}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

function PasteIntake({ run }) {
  const [text, setText] = useState('')
  return (
    <div style={{ display: 'grid', gap: 'var(--gap)' }}>
      <Field label="Paste the leaked passage">
        <Textarea rows={7} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the text you recovered from the leak…" />
      </Field>
      <div>
        <Button variant="primary" disabled={!text.trim()} onClick={() => run.run(() => api.leakcheck({ text })).catch(() => {})}>Trace this text</Button>
      </div>
    </div>
  )
}
