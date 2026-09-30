import { useRef, useState } from 'react'
import { api } from '@/api.js'
import { useAsync } from './_shared/useAsync.jsx'
import { Loading, ErrorState } from './_shared/Async.jsx'
import { Button, Field, Panel, Tabs, Textarea, mono, Workspace, PageHead } from './_shared/ui.jsx'
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
  { id: 'example', label: 'Built-in example' },
  { id: 'paste', label: 'Paste suspect text' },
]

export default function Anvesana() {
  const [mode, setMode] = useState('example')
  const run = useAsync()

  return (
    <Workspace max={1360}>
      <PageHead
        title="Anveṣaṇa"
        sub="Two separate answers — which document, and whose copy. Never one verdict."
      />

      <Panel>
        <Tabs tabs={MODES} active={mode} onChange={setMode} />
        <div style={{ paddingTop: 'calc(var(--gap) * 1.25)' }}>
          {mode === 'upload' && <UploadIntake run={run} />}
          {mode === 'example' && <ExampleIntake run={run} />}
          {mode === 'paste' && <PasteIntake run={run} />}
        </div>
      </Panel>

      {run.status === 'loading' ? (
        <div style={{ marginTop: 'calc(var(--gap) * 1.5)' }}><Panel><Loading steps={['extracting the leaked text', 'aligning against the sealed corpus', 'recovering the watermark', 'ranking likely recipients']} activeStep={2} /></Panel></div>
      ) : run.status === 'error' ? (
        <div style={{ marginTop: 'calc(var(--gap) * 1.5)' }}><ErrorState error={run.error} onRetry={run.retry} /></div>
      ) : run.status === 'success' ? (
        <div className="lb-fade" style={{ marginTop: 'calc(var(--gap) * 1.5)' }}><Findings result={run.data} /></div>
      ) : null}
    </Workspace>
  )
}

function UploadIntake({ run }) {
  const inputRef = useRef(null)
  const [name, setName] = useState('')
  const pick = (file) => { if (!file) return; setName(file.name); run.run(() => api.uploadLeak(file)).catch(() => {}) }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <Button variant="primary" onClick={() => inputRef.current?.click()}>Choose a leaked file</Button>
      <span style={{ fontSize: 12, color: 'var(--ink-faint)' }}>PDF, image, or text — extracted before the mark is read.</span>
      {name ? <span style={{ ...mono, fontSize: 12, color: 'var(--ink-muted)' }}>{name}</span> : null}
      <input ref={inputRef} type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.txt,.md,image/*,text/*" onChange={(e) => pick(e.target.files?.[0])} />
    </div>
  )
}

function ExampleIntake({ run }) {
  const KINDS = [
    { id: 'text', name: 'Leaked text', sub: 'a copied-out passage' },
    { id: 'screenshot', name: 'Screenshot', sub: 'a photographed page (OCR)' },
    { id: 'collusion', name: 'Collusion', sub: 'two copies averaged' },
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 10 }}>
      {KINDS.map((k) => (
        <button
          key={k.id}
          type="button"
          className="lb-card"
          onClick={() => run.run(() => api.example(k.id).then((ex) => api.leakcheck({ text: ex.leaked_text, image_b64: ex.image_b64 }))).catch(() => {})}
          style={{ textAlign: 'left', background: 'var(--bg-panel)', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', padding: '14px', cursor: 'pointer', color: 'var(--ink)' }}
        >
          <div style={{ fontFamily: 'var(--font-display)', fontWeight: 500 }}>{k.name}</div>
          <div style={{ fontSize: 12, color: 'var(--ink-muted)', marginTop: 4 }}>{k.sub}</div>
        </button>
      ))}
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
