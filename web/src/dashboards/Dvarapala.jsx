import { useEffect, useMemo, useState } from 'react'
import { api } from '@/api.js'
import { WitnessRing } from '@/components'
import { useAsync } from './_shared/useAsync.jsx'
import { mono, Workspace, Panel } from './_shared/ui.jsx'
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
    <Workspace max={2400} style={{ height: 'calc(100dvh - var(--strip-h))', display: 'flex', flexDirection: 'column', padding: 'var(--gap)' }}>
      <Panel pad={0} style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'stretch', overflow: 'hidden' }}>
        <div style={{ width: 'var(--rail-w)', flex: '0 0 var(--rail-w)', borderRight: '1px solid var(--hairline)', padding: 'calc(var(--gap) * 1.5)', display: 'flex', flexDirection: 'column', gap: 'calc(var(--gap) * 1.5)', minHeight: 0 }}>
          <StepRail current={step} reached={reached} onGo={go} />
          <div style={{ marginTop: 'auto', display: 'grid', gap: 'var(--gap)' }}>
            <LedgerPulse />
          </div>
        </div>

        <main className="lb-fade lb-scroll" key={step} style={{ flex: 1, minWidth: 0, padding: 'calc(var(--gap) * 2)', overflow: 'auto' }}>
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
      </Panel>
    </Workspace>
  )
}

/**
 * The witnessed ledger, docked under the step rail as compact context (not a
 * floating fourth column). Sealing writes nothing here — the gate is honest: the
 * record grows only when a recipient opens — so this is the book the seal will
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
    <aside style={{ border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', background: 'var(--bg-panel)', padding: 'var(--gap)', display: 'flex', alignItems: 'center', gap: 12 }}>
      {data ? <WitnessRing scale="strip" data={data} /> : <div style={{ width: 44, height: 44, flex: '0 0 44px' }} />}
      <div style={{ minWidth: 0 }}>
        <div style={{ ...mono, fontSize: 18, color: 'var(--ink)', lineHeight: 1 }}>{data ? data.leaves : '—'}</div>
        <div style={{ fontSize: 11, color: 'var(--ink-faint)', marginTop: 3 }}>
          leaves recorded{data ? ` · ${data.witnesses} witnesses` : ''}
        </div>
      </div>
    </aside>
  )
}
