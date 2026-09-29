/**
 * Lane-B-local UI kit. Small token-styled helpers so the dashboards read as one
 * instrument without reaching into Lane A's (unfrozen) design-system primitives.
 * Every value is a CSS token var — no hardcoded hex, sharp 2–6px corners, one
 * accent per screen (the caller decides where the accent lands).
 */
import { forwardRef } from 'react'

export const shortHash = (h, head = 6, tail = 4) => {
  if (!h || typeof h !== 'string') return '—'
  if (h.length <= head + tail + 1) return h
  return `${h.slice(0, head)}…${h.slice(-tail)}`
}

export const mono = { fontFamily: 'var(--font-mono)' }

export function Panel({ children, pad = 1.25, style, className = '', ...rest }) {
  return (
    <div
      className={className}
      style={{
        border: '1px solid var(--hairline)',
        borderRadius: 'var(--radius)',
        background: 'var(--bg-panel)',
        padding: `calc(var(--gap) * ${pad})`,
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  )
}

export function SectionTitle({ children, sub }) {
  return (
    <div style={{ marginBottom: 'var(--gap)' }}>
      <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 15, color: 'var(--ink)' }}>
        {children}
      </div>
      {sub ? (
        <div style={{ color: 'var(--ink-muted)', fontSize: 13, marginTop: 2 }}>{sub}</div>
      ) : null}
    </div>
  )
}

const btnBase = {
  font: 'inherit',
  fontWeight: 500,
  borderRadius: 'var(--radius)',
  padding: '9px 16px',
  cursor: 'pointer',
  border: '1px solid var(--hairline)',
  background: 'transparent',
  color: 'var(--ink)',
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
}

export const Button = forwardRef(function Button(
  { variant = 'ghost', style, className = '', children, ...rest },
  ref,
) {
  const variants = {
    ghost: {},
    primary: {
      border: '1px solid var(--accent-soft)',
      color: 'var(--accent)',
      fontFamily: 'var(--font-display)',
    },
    quiet: { border: '1px solid transparent', color: 'var(--ink-muted)', padding: '6px 10px' },
  }
  return (
    <button
      ref={ref}
      className={`lb-btn ${variant === 'primary' ? 'lb-btn--primary' : ''} ${className}`}
      style={{ ...btnBase, ...variants[variant], ...style }}
      {...rest}
    >
      {children}
    </button>
  )
})

export function Field({ label, hint, children }) {
  return (
    <label style={{ display: 'block' }}>
      {label ? (
        <span style={{ display: 'block', fontSize: 12, color: 'var(--ink-muted)', marginBottom: 6, letterSpacing: '0.02em' }}>
          {label}
        </span>
      ) : null}
      {children}
      {hint ? <span style={{ display: 'block', fontSize: 12, color: 'var(--ink-faint)', marginTop: 6 }}>{hint}</span> : null}
    </label>
  )
}

const inputBase = {
  width: '100%',
  font: 'inherit',
  color: 'var(--ink)',
  background: 'var(--bg)',
  border: '1px solid var(--hairline)',
  borderRadius: 'var(--radius)',
  padding: '9px 12px',
  outline: 'none',
}

export function Input(props) {
  return <input {...props} style={{ ...inputBase, ...props.style }} />
}
export function Textarea(props) {
  return <textarea {...props} style={{ ...inputBase, resize: 'vertical', lineHeight: 1.5, ...props.style }} />
}

/** A status pill. `tone` maps to reserved colours only where earned. */
export function Pill({ tone = 'neutral', children }) {
  const tones = {
    neutral: { color: 'var(--ink-muted)', border: 'var(--hairline)' },
    accent: { color: 'var(--accent)', border: 'var(--accent-soft)' },
    verified: { color: 'var(--verified)', border: 'var(--verified)' },
    alert: { color: 'var(--alert)', border: 'var(--alert)' },
    struct: { color: 'var(--struct-2)', border: 'var(--hairline)' },
  }
  const t = tones[tone] || tones.neutral
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        color: t.color,
        border: `1px solid ${t.border}`,
        borderRadius: 'var(--radius)',
        padding: '2px 8px',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  )
}

export function Tabs({ tabs, active, onChange }) {
  return (
    <div role="tablist" style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--hairline)' }}>
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={active === t.id}
          className={`lb-tab ${active === t.id ? 'lb-tab--on' : ''}`}
          onClick={() => onChange(t.id)}
          style={{
            background: 'transparent',
            border: 'none',
            borderBottom: '2px solid transparent',
            color: active === t.id ? 'var(--accent)' : 'var(--ink-muted)',
            font: 'inherit',
            padding: '8px 12px',
            cursor: 'pointer',
            marginBottom: -1,
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

/** Two-line "big number" for confidences — the mono, exact instrument read. */
export function Metric({ label, value, tone = 'neutral', suffix }) {
  const color = tone === 'accent' ? 'var(--accent)' : tone === 'struct' ? 'var(--struct-2)' : 'var(--ink)'
  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--ink-muted)', letterSpacing: '0.02em' }}>{label}</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 26, color, lineHeight: 1.1, marginTop: 4 }}>
        {value}
        {suffix ? <span style={{ fontSize: 13, color: 'var(--ink-muted)', marginLeft: 4 }}>{suffix}</span> : null}
      </div>
    </div>
  )
}
