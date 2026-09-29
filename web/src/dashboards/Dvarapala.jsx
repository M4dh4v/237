import { useEffect, useMemo, useState } from 'react'
import { api } from '@/api.js'
import { WitnessRing } from '@/components'
import { useAsync } from './_shared/useAsync.jsx'
import { mono } from './_shared/ui.jsx'
import StepRail, { STEPS } from './dvarapala/StepRail.jsx'
import SourceStep from './dvarapala/SourceStep.jsx'
import RecipientStep from './dvarapala/RecipientStep.jsx'
import ClassifyStep from './dvarapala/ClassifyStep.jsx'
import SealStep from './dvarapala/SealStep.jsx'
import './dashboards.css'

/**
 * Dvārapāla — the gatekeeper (design plan §7). The sender's whole job is one
 * deliberate act split into four honest steps: choose a source, choose who is
 * inside, set the handling label, and seal. The step rail is both map and
 * progress; the right rail keeps the live ledger in view so the sender always
 * sees the witnessed record their seal will (eventually) extend.
 */
const ORDER = STEPS.map((s) => s.id)

export default function Dvarapala() {
  const [step, setStep] = useState('source')
  const [reached, setReached] = useState(() => new Set(['source']))
  const [source, setSource] = useState(null)
  const [recipients, setRecipients] = useState([])
  const [level, setLevel] = useState('UNCLASSIFIED')

  const go = (id) => {
    setStep(id)
    setReached((r) => new Set(r).add(id))
  }
  const advance = () => go(ORDER[Math.min(ORDER.length - 1, ORDER.indexOf(step) + 1)])
  const back = () => go(ORDER[Math.max(0, ORDER.indexOf(step) - 1)])
  const restart = () => { setSource(null); setRecipients([]); setLevel('UNCLASSIFIED'); setReached(new Set(['source'])); setStep('source') }

  return (
    <div style={{ display: 'flex', gap: 'calc(var(--gap) * 1.5)', padding: 'calc(var(--gap) * 1.5)', alignItems: 'flex-start' }}>
      <StepRail current={step} reached={reached} onGo={go} />

      <main className="lb-fade" key={step} style={{ flex: 1, minWidth: 0 }}>
        {step === 'source' && (
          <SourceStep source={source} onSource={(s) => { setSource(s); setReached((r) => new Set(r).add('recipients')) }} onNext={advance} />
        )}
        {step === 'recipients' && (
          <RecipientStep selected={recipients} onSelected={setRecipients} onNext={advance} onBack={back} />
        )}
        {step === 'classification' && (
          <ClassifyStep level={level} onLevel={setLevel} onNext={advance} onBack={back} />
        )}
        {step === 'seal' && (
          <SealStep source={source} recipients={recipients} level={level} onBack={source && recipients.length ? back : restart} />
        )}
      </main>

      <LedgerPulse />
    </div>
  )
}

/**
 * The right rail: the live witnessed ledger, at strip scale. Sealing writes
 * nothing here (the gate is honest — the record grows only when a recipient
 * opens), so this is context, not a progress bar: it is the book the seal will
 * one day be recorded in, held by many witnesses at once.
 */
function LedgerPulse() {
  const head = useAsync()
  useEffect(() => { head.run(() => api.ledgerHead()) }, []) // eslint-disable-line

  const data = useMemo(() => {
    const d = head.data
    if (!d) return null
    const witnesses = Array.isArray(d.witnesses) ? d.witnesses.length : d.min_witnesses ?? 3
    return { leaves: d.tree_size ?? 0, witnesses }
  }, [head.data])

  return (
    <aside style={{ width: 200, flex: '0 0 200px', position: 'sticky', top: 'calc(var(--gap) * 1.5)' }}>
      <div style={{ ...mono, fontSize: 11, color: 'var(--ink-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>the ledger</div>
      <div style={{ border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', background: 'var(--bg-panel)', padding: 'var(--gap)', display: 'grid', gap: 10, placeItems: 'center' }}>
        {data ? <WitnessRing scale="strip" data={data} /> : <div style={{ width: 48, height: 48 }} />}
        <div style={{ textAlign: 'center' }}>
          <div style={{ ...mono, fontSize: 20, color: 'var(--ink)' }}>{data ? data.leaves : '—'}</div>
          <div style={{ fontSize: 11, color: 'var(--ink-faint)' }}>leaves recorded</div>
        </div>
      </div>
      <p style={{ margin: '10px 0 0', fontSize: 11, color: 'var(--ink-faint)', lineHeight: 1.45 }}>
        {data ? `${data.witnesses} witnesses co-sign this record.` : ''} Sealing adds nothing here — the ledger grows only when a copy is opened.
      </p>
    </aside>
  )
}
