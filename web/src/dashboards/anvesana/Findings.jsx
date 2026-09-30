import { useMemo, useState } from 'react'
import { WitnessRing, PresentNotVerified, Caveat } from '@/components'
import { Panel, Pill, mono } from '../_shared/ui.jsx'
import { CertificateLauncher } from '../Pramanapatra.jsx'

/**
 * Findings — the result of an investigation (design plan §9, sakshya-honesty §5).
 *
 * The single rule this component exists to enforce: DOCUMENT MATCH and RECIPIENT
 * ATTRIBUTION are two separate answers with two separate confidences, shown side
 * by side, never averaged into one number. A leak can be a certain document and
 * an uncertain person at the same time — that is the normal, honest state, and
 * collapsing it would be a lie the whole tool is built to refuse.
 *
 * The intake gives us two response shapes — the raw pipeline result from
 * /leakcheck and the normalised shape from uploadLeak — so we fold both into one
 * view model first, then render once.
 */
export default function Findings({ result }) {
  const v = useMemo(() => normalize(result), [result])

  return (
    <div style={{ display: 'grid', gap: 'calc(var(--gap) * 2)' }}>
      <section>
        <SectionLabel>the two answers</SectionLabel>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 'calc(var(--gap) * 1.5)' }}>
          <DocumentPanel doc={v.document} />
          <AttributionPanel attr={v.attribution} candidates={v.candidates} status={v.status} />
        </div>
      </section>

      {v.candidates.length > 1 ? <Ranking candidates={v.candidates} /> : null}

      <LedgerLink attr={v.attribution} />

      {v.verification ? <Verification report={v.verification} /> : null}

      {v.caveat || v.simulated ? (
        <div style={{ display: 'grid', gap: 'var(--gap)' }}>
          {v.simulated ? <Caveat kind="simulated" /> : null}
          {v.caveat ? (
            <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-faint)', lineHeight: 1.5 }}>{v.caveat}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

/** Fold both response shapes into one honest view model. */
function normalize(r) {
  if (!r) return { document: {}, attribution: {}, candidates: [] }
  // Normalised uploadLeak shape.
  if (r.documentMatch || r.recipientAttribution) {
    const a = r.recipientAttribution || {}
    return {
      status: a.recipientId ? 'attributed' : 'unidentified',
      document: { docId: r.documentMatch?.docId, confidence: r.documentMatch?.confidence, ambiguous: false, candidates: [] },
      attribution: { recovered: !!a.recipientId, confidence: a.confidence, leaf: a.leaf, recipientId: a.recipientId, tardos: {} },
      candidates: a.recipientId ? [{ recipient_id: a.recipientId, ledger_index: a.leaf, crosses_threshold: true, source: 'ledger-pointer' }] : [],
      verification: null,
      caveat: null,
      pages: r.pages || [],
    }
  }
  // Raw /leakcheck (Investigation.as_dict).
  const doc = r.document || {}
  const wm = r.watermark || {}
  const cands = r.candidates || []
  return {
    status: r.status,
    document: { docId: doc.doc_id, confidence: doc.confidence, ambiguous: doc.ambiguous, candidates: doc.candidates || [] },
    attribution: {
      recovered: !!wm.recovered,
      confidence: wm.confidence,
      leaf: wm.ledger_index,
      recipientId: cands[0]?.crosses_threshold ? cands[0]?.recipient_id : null,
      tardos: { positions: wm.tardos_positions, required: wm.tardos_required, guarantee: wm.tardos_guarantee },
    },
    candidates: cands,
    verification: r.verification || null,
    caveat: r.caveat,
    simulated: Array.isArray(r.simulated) && r.simulated.length > 0,
  }
}

function DocumentPanel({ doc }) {
  const hasDoc = doc.docId != null
  return (
    <Panel style={{ display: 'grid', gap: 12 }}>
      <PanelHead>which document</PanelHead>
      {hasDoc ? (
        <>
          <div style={{ ...mono, fontSize: 20, color: 'var(--ink)' }}>{doc.docId}</div>
          <Bar value={doc.confidence} color="var(--struct-1)" label="alignment against the sealed corpus" />
          {doc.ambiguous ? (
            <p style={{ margin: 0, fontSize: 12, color: 'var(--accent-soft)', lineHeight: 1.5 }}>
              More than one document aligns closely — the top match is not decisive alone.
            </p>
          ) : null}
        </>
      ) : (
        <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
          No document in the sealed corpus aligns with this text.
        </p>
      )}
    </Panel>
  )
}

function AttributionPanel({ attr, candidates, status }) {
  const named = attr.recipientId
  const top = candidates[0]
  return (
    <Panel style={{ display: 'grid', gap: 12 }}>
      <PanelHead>whose copy</PanelHead>
      {named ? (
        <>
          <div style={{ ...mono, fontSize: 20, color: 'var(--ink)' }}>{named}</div>
          <Bar value={attr.confidence} color="var(--accent)" label="watermark recovery confidence" />
          {attr.tardos?.positions != null ? (
            <div style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)' }}>
              {attr.tardos.positions}/{attr.tardos.required} mark positions · {attr.tardos.guarantee} guarantee
            </div>
          ) : null}
        </>
      ) : (
        <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
          {status === 'collusion-suspected'
            ? 'The mark carries more than one recipient — no single copy is named. See the ranking below.'
            : status === 'no-watermark'
            ? 'No recoverable mark survived, so no copy can be named.'
            : top
            ? 'A candidate leads but does not cross the accusation threshold — not enough to name a copy.'
            : 'No attribution: the mark did not decode to a recipient.'}
        </p>
      )}
    </Panel>
  )
}

function Ranking({ candidates }) {
  return (
    <Panel style={{ display: 'grid', gap: 'var(--gap)' }}>
      <div>
        <PanelHead>ranked candidates</PanelHead>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
          The collusion case: each copy the mark touches, with its evidence. A rank is not an accusation.
        </p>
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {candidates.map((c, i) => (
          <div key={c.recipient_id || i} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', background: 'var(--bg)' }}>
            <span style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)', width: 20 }}>#{i + 1}</span>
            <span style={{ ...mono, fontSize: 13, flex: 1 }}>{c.recipient_id}</span>
            {c.tardos_score != null ? (
              <span style={{ ...mono, fontSize: 11, color: 'var(--ink-muted)' }}>score {c.tardos_score} / thr {c.tardos_threshold}</span>
            ) : null}
            <Pill tone={c.crosses_threshold ? 'struct' : 'neutral'}>
              {c.crosses_threshold ? 'crosses threshold' : 'below threshold'}
            </Pill>
          </div>
        ))}
      </div>
      <Caveat kind="ranking" />
    </Panel>
  )
}

function LedgerLink({ attr }) {
  if (attr.leaf == null) return null
  return (
    <Panel style={{ display: 'grid', gap: 'calc(var(--gap) * 1.25)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0,1fr)', gap: 'calc(var(--gap) * 1.5)', alignItems: 'center' }}>
        <WitnessRing scale="widget" data={{ witnesses: 3 }} highlightLeaf={attr.leaf} />
        <div style={{ display: 'grid', gap: 6 }}>
          <PanelHead>the entry it points at</PanelHead>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--ink-muted)', lineHeight: 1.5 }}>
            The mark is a pointer to one leaf of the witnessed ledger — the open that released this copy.
          </p>
          <div style={{ ...mono, fontSize: 14, color: 'var(--ink)' }}>leaf #{attr.leaf}</div>
        </div>
      </div>
      <CertificateLauncher findingId={attr.leaf} />
    </Panel>
  )
}

/**
 * Present-not-verified: we show the pipeline's own verification checks as a
 * checklist of what it re-derived, never as a green "verified" badge. Folded
 * into a disclosure so the default result stays calm — the detail is one click
 * away, not a wall. The shared component owns the "not verified here" wording.
 */
function Verification({ report }) {
  const checks = [
    ['request signature', report.request_signature_ok],
    ['inclusion proof', report.inclusion_ok],
    ['head signature', report.sth_signature_ok],
    ['witness quorum', report.witness_quorum_ok],
  ]
  return (
    <Disclosure label="what was re-checked">
      <div style={{ display: 'grid', gap: 6, marginBottom: 'var(--gap)' }}>
        {checks.map(([k, ok]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '2px 0' }}>
            <span style={{ color: 'var(--ink-muted)' }}>{k}</span>
            <span style={{ ...mono, fontSize: 12, color: ok ? 'var(--ink)' : 'var(--alert)' }}>{ok ? 're-derived' : 'did not hold'}</span>
          </div>
        ))}
      </div>
      {report.index != null ? <div style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)', marginBottom: 10 }}>ledger entry #{report.index}</div> : null}
      <PresentNotVerified />
    </Disclosure>
  )
}

/** A quiet native expander — secondary detail folded away by default. */
function Disclosure({ label, children }) {
  return (
    <details className="lb-disclosure">
      <summary style={{ ...mono, fontSize: 11, color: 'var(--ink-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', cursor: 'pointer', listStyle: 'none', padding: '4px 0' }}>
        {label}
      </summary>
      <div style={{ paddingTop: 'var(--gap)' }}>{children}</div>
    </details>
  )
}

function SectionLabel({ children }) {
  return (
    <div style={{ ...mono, fontSize: 11, color: 'var(--ink-faint)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 10 }}>
      {children}
    </div>
  )
}

function PanelHead({ children }) {
  return (
    <div style={{ ...mono, fontSize: 11, color: 'var(--ink-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 10 }}>
      {children}
    </div>
  )
}

/** A confidence as a bar, never a verdict. Value is 0..1. */
function Bar({ value, color, label }) {
  const frac = Math.max(0, Math.min(1, Number(value) || 0))
  return (
    <div>
      <div style={{ height: 8, borderRadius: 4, background: 'var(--bg-elevated)', overflow: 'hidden', border: '1px solid var(--hairline)' }}>
        <div style={{ height: '100%', width: '100%', background: color, transformOrigin: 'left', transform: `scaleX(${frac})`, transition: 'transform .5s ease' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 5 }}>
        <span style={{ fontSize: 11, color: 'var(--ink-faint)' }}>{label}</span>
        <span style={{ ...mono, fontSize: 11, color: 'var(--ink-muted)' }}>{(frac * 100).toFixed(0)}%</span>
      </div>
    </div>
  )
}
