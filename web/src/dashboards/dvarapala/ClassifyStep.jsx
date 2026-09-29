import { ClassificationBanner } from '@/components'
import { StepFooter } from './RecipientStep.jsx'

/**
 * Step 3 — classification (design plan §7.3, §11). A single banded choice that
 * stamps the document's handling label. It is a label, not an alert, so the
 * chips stay neutral and only the *selected* band earns emphasis; the reserved
 * alert colour is never spent here. A live banner preview shows exactly what
 * will ride at the top of every recipient's copy.
 */
const LEVELS = [
  { id: 'UNCLASSIFIED', note: 'no handling restriction' },
  { id: 'RESTRICTED', note: 'need-to-know within command' },
  { id: 'CONFIDENTIAL', note: 'damage to national security if disclosed' },
  { id: 'SECRET', note: 'serious damage if disclosed' },
]

export default function ClassifyStep({ level, onLevel, onNext, onBack }) {
  const current = level || 'UNCLASSIFIED'
  return (
    <div>
      <h3 style={{ fontSize: 20 }}>How is it marked</h3>
      <p style={{ color: 'var(--ink-muted)', margin: '6px 0 0', maxWidth: 560, lineHeight: 1.5 }}>
        This sets the handling banner stamped on every copy. It is a label the reader sees — the
        forensic mark is separate and invisible.
      </p>

      <div style={{ marginTop: 'var(--gap)', display: 'grid', gap: 8, maxWidth: 560 }}>
        {LEVELS.map((l) => {
          const on = current === l.id
          return (
            <button
              key={l.id}
              type="button"
              className={`lb-card ${on ? 'lb-card--on' : ''}`}
              onClick={() => onLevel(l.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 14, textAlign: 'left',
                background: 'var(--bg-panel)', border: '1px solid var(--hairline)',
                borderRadius: 'var(--radius)', padding: '12px 14px', cursor: 'pointer', color: 'var(--ink)',
              }}
            >
              <span aria-hidden style={{
                width: 12, height: 12, borderRadius: '50%', flex: '0 0 12px',
                border: `1px solid ${on ? 'var(--accent)' : 'var(--hairline)'}`,
                background: on ? 'var(--accent)' : 'transparent',
              }} />
              <span style={{ ...({ fontFamily: 'var(--font-mono)' }), fontSize: 13, letterSpacing: '0.06em', minWidth: 130 }}>{l.id}</span>
              <span style={{ fontSize: 12, color: 'var(--ink-muted)' }}>{l.note}</span>
            </button>
          )
        })}
      </div>

      <div style={{ marginTop: 'calc(var(--gap) * 1.5)' }}>
        <div style={{ fontSize: 12, color: 'var(--ink-muted)', marginBottom: 8, letterSpacing: '0.04em', textTransform: 'uppercase', fontFamily: 'var(--font-mono)' }}>banner preview</div>
        <div style={{ border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
          <ClassificationBanner level={current} position="top" />
          <div style={{ padding: 'calc(var(--gap) * 1.5)', color: 'var(--ink-faint)', fontSize: 13, textAlign: 'center' }}>
            …the recipient's document renders here…
          </div>
        </div>
      </div>

      <StepFooter onBack={onBack} onNext={onNext} nextLabel="Review & seal →" />
    </div>
  )
}
