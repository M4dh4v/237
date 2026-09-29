/* Design-system primitives (design plan §4, contract §1). Token-only, presentational.
 * Import from '@/design-system' (barrel below). Styles live in primitives.css.
 *
 * The one law: .btn--primary is the single accent action per screen. Do not
 * paint two things with the accent.
 */
import { useState } from 'react'
import './primitives.css'

export function Button({ variant = 'ghost', size = 'md', hint, className = '', children, ...rest }) {
  const cls = [
    'btn',
    variant === 'primary' && 'btn--primary',
    variant === 'ghost' && 'btn--ghost',
    variant === 'quiet' && 'btn--quiet',
    size === 'sm' && 'btn--sm',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  const btn = (
    <button type="button" className={cls} {...rest}>
      {children}
    </button>
  )
  // disabled + hint: the backend-unreachable pattern (§7.5)
  if (hint && rest.disabled) {
    return (
      <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
        {btn}
        <span className="btn__hint">{hint}</span>
      </span>
    )
  }
  return btn
}

export function Panel({ elevated = false, pad = true, className = '', children, ...rest }) {
  const cls = ['panel', elevated && 'panel--elevated', pad && 'panel__pad', className]
    .filter(Boolean)
    .join(' ')
  return (
    <div className={cls} {...rest}>
      {children}
    </div>
  )
}

export function Chip({ selectable = false, selected = false, className = '', children, ...rest }) {
  const cls = [
    'chip',
    selectable && 'chip--selectable',
    selected && 'chip--selected',
    className,
  ]
    .filter(Boolean)
    .join(' ')
  const isButton = selectable
  const Tag = isButton ? 'button' : 'span'
  return (
    <Tag
      className={cls}
      {...(isButton ? { type: 'button', 'aria-pressed': selected } : {})}
      {...rest}
    >
      {children}
    </Tag>
  )
}

export function Banner({ tone = 'struct', className = '', children, ...rest }) {
  // tone only shifts the left rule; body stays quiet. Reserved colours are not
  // spent here — this is a neutral notice, not a status.
  const cls = ['banner', className].filter(Boolean).join(' ')
  const rule =
    tone === 'accent' ? 'var(--accent-soft)' : tone === 'struct' ? 'var(--struct-2)' : 'var(--hairline)'
  return (
    <div className={cls} style={{ borderLeftColor: rule }} {...rest}>
      {children}
    </div>
  )
}

/**
 * Mono hash/key/ID display. Long values ellipsis in the middle (head…tail) so
 * both ends stay readable; click to copy; hover title shows the full value.
 * A hash in a proportional font is a bug — this is always --font-mono.
 */
export function Hash({ value = '', head = 8, tail = 8, className = '', label }) {
  const [copied, setCopied] = useState(false)
  const str = String(value)
  const shown =
    str.length > head + tail + 1 ? `${str.slice(0, head)}…${str.slice(-tail)}` : str

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(str)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      /* clipboard unavailable (air-gapped file://) — the title still shows it */
    }
  }

  return (
    <button
      type="button"
      className={['hash', className].filter(Boolean).join(' ')}
      title={label ? `${label}: ${str}` : str}
      onClick={copy}
    >
      <span>{shown}</span>
      {copied ? <span className="hash__copied">copied</span> : null}
    </button>
  )
}
