import { useEffect, useState } from 'react'

/**
 * The thin rail that names the three acts and tracks where the reader is.
 *
 * This is navigation, not a set of tabs: every act is on the page at once and
 * the story reads top to bottom. The rail only reflects and shortcuts that
 * scroll -- clicking an act jumps to it, and the act the viewport is currently
 * over is highlighted -- so a presenter can move without hunting, and a first
 * reader can still just scroll and never touch it.
 */
const ACTS = [
  { id: 'act-live', label: 'I · Distribute → decrypt → attribute' },
  { id: 'act-tamper', label: 'II · Tamper' },
  { id: 'act-robustness', label: 'III · Robustness & one honest limit' },
]

export default function ActRail() {
  const [active, setActive] = useState(ACTS[0].id)

  useEffect(() => {
    const sections = ACTS.map((a) => document.getElementById(a.id)).filter(Boolean)
    if (sections.length === 0) return
    // The section whose top most recently crossed the upper third of the
    // viewport wins. A plain "is intersecting" test lights two acts at once on
    // a tall screen; anchoring the trigger line high keeps it to one.
    const obs = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '-30% 0px -60% 0px', threshold: 0 },
    )
    sections.forEach((s) => obs.observe(s))
    return () => obs.disconnect()
  }, [])

  return (
    <nav className="actrail" aria-label="demo acts">
      {ACTS.map((a) => (
        <a
          key={a.id}
          href={`#${a.id}`}
          className={active === a.id ? 'actrail-link active' : 'actrail-link'}
          aria-current={active === a.id ? 'step' : undefined}
        >
          {a.label}
        </a>
      ))}
    </nav>
  )
}
