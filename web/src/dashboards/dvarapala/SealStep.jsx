import { api } from '@/api.js'
import SealScene from '@/scenes/SealScene.jsx'
import { useAsync } from '../_shared/useAsync.jsx'
import { ErrorState, Loading } from '../_shared/Async.jsx'
import { Button, Panel, Pill, mono, shortHash } from '../_shared/ui.jsx'
import { StepFooter } from './RecipientStep.jsx'

/**
 * Step 4 — the seal (design plan §7.4). One deliberate act. The review shows
 * exactly what is about to be sealed to whom; arming calls distribute, and the
 * SealScene closes UNOPENED. The caption is the whole honesty of the gate: the
 * ledger stays empty until a recipient actually opens a copy — sealing writes
 * nothing, so there is nothing yet to rewrite.
 */
export default function SealStep({ source, recipients, level, onBack }) {
  const seal = useAsync()
  const arm = () =>
    seal.run(() =>
      api.distribute({ doc_id: source.docId, classification: level || 'UNCLASSIFIED', recipients }),
    ).catch(() => {})

  const done = seal.status === 'success'
  const receipt = seal.data

  return (
    <div>
      <h3 style={{ fontSize: 20 }}>{done ? 'Sealed' : 'Review & seal'}</h3>
      <p style={{ color: 'var(--ink-muted)', margin: '6px 0 0', maxWidth: 560, lineHeight: 1.5 }}>
        {done
          ? 'The same file is sealed for every recipient, each with its own mark. The gate is armed.'
          : 'One deliberate act. Confirm what is about to leave the gate.'}
      </p>

      <div style={{ marginTop: 'var(--gap)', display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,360px)', gap: 'calc(var(--gap) * 1.5)', alignItems: 'start' }}>
        <Panel>
          <Row label="Document">
            <span style={{ ...mono, fontSize: 13 }}>{source?.title || source?.docId}</span>
            <span style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)', display: 'block', marginTop: 2 }}>id {shortHash(source?.docId, 10, 4)}</span>
          </Row>
          <Row label="Classification"><Pill tone="neutral">{level || 'UNCLASSIFIED'}</Pill></Row>
          <Row label={`Recipients (${recipients.length})`} last>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {recipients.map((r) => <span key={r} style={{ ...mono, fontSize: 12, color: 'var(--ink-muted)', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', padding: '2px 8px' }}>{r}</span>)}
            </div>
          </Row>

          {done && receipt ? (
            <div style={{ marginTop: 'var(--gap)', paddingTop: 'var(--gap)', borderTop: '1px solid var(--hairline)', display: 'grid', gap: 8, fontSize: 12 }}>
              <KV k="grants" v={`${receipt.grants?.length ?? recipients.length} recipient(s)`} />
              <KV k="doc hash" v={shortHash(receipt.doc_hash, 12, 8)} mono />
              {receipt.container_bytes != null ? <KV k="container" v={`${receipt.container_bytes.toLocaleString()} bytes`} /> : null}
            </div>
          ) : null}

          {seal.status === 'error' ? <div style={{ marginTop: 'var(--gap)' }}><ErrorState error={seal.error} onRetry={seal.retry} /></div> : null}
        </Panel>

        <Panel>
          {seal.status === 'loading' ? (
            <Loading steps={['wrapping the content key to the authority', 'binding each recipient mark', 'packing the sealed container']} activeStep={1} />
          ) : (
            <>
              <SealScene sealed={done} recipients={recipients.length} />
              <p style={{ margin: 'var(--gap) 0 0', fontSize: 13, color: done ? 'var(--ink)' : 'var(--ink-muted)', lineHeight: 1.5, textAlign: 'center' }}>
                {done
                  ? 'Sealed. Nothing is written to the ledger until a recipient opens it — that is the gate.'
                  : 'When you arm, one light-strand per recipient wraps the core into a single sealed crystal.'}
              </p>
            </>
          )}
        </Panel>
      </div>

      {done ? (
        <div style={{ marginTop: 'calc(var(--gap) * 1.5)', paddingTop: 'var(--gap)', borderTop: '1px solid var(--hairline)' }}>
          <Button variant="quiet" onClick={onBack}>← Seal another</Button>
        </div>
      ) : (
        <StepFooter onBack={onBack} onNext={arm} nextLabel="Arm & seal" nextDisabled={!source || !recipients.length} />
      )}
    </div>
  )
}

function Row({ label, children, last }) {
  return (
    <div style={{ display: 'flex', gap: 'var(--gap)', padding: '10px 0', borderBottom: last ? 'none' : '1px solid var(--hairline)' }}>
      <div style={{ width: 130, flex: '0 0 130px', fontSize: 12, color: 'var(--ink-muted)' }}>{label}</div>
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  )
}

function KV({ k, v, mono: isMono }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
      <span style={{ color: 'var(--ink-muted)' }}>{k}</span>
      <span style={isMono ? mono : undefined} >{v}</span>
    </div>
  )
}
