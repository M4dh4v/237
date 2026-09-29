/* Dev-only design gallery — every primitive + honesty component in its states,
 * so the surface can be screenshotted and self-critiqued against the anti-slop
 * and honesty rules. Routed at /_ds; not linked in product nav. Not shipped in
 * the pitch flow.
 */
import { Button, Panel, Chip, Banner, Hash } from './index.js'
import {
  StatusStrip,
  PresentNotVerified,
  FailClosed,
  Caveat,
  ClassificationBanner,
  SceneFallback,
} from '@/components/index.js'

const Section = ({ title, children }) => (
  <section style={{ marginBottom: 'var(--space-7)' }}>
    <h3 style={{ fontSize: 'var(--text-md)', color: 'var(--ink-muted)', fontWeight: 500, marginBottom: 'var(--space-4)', fontFamily: 'var(--font-mono)' }}>
      {title}
    </h3>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-4)', alignItems: 'flex-start' }}>
      {children}
    </div>
  </section>
)

export default function Gallery() {
  return (
    <div>
      <StatusStrip
        offline
        ledgerLeaves={7}
        quorum={{ have: 3, need: 3 }}
        witnessesUp={3}
        liteMode={false}
        onToggleLite={() => {}}
        onRoleSwitch={() => {}}
      />
      <div style={{ padding: 'var(--space-6)', maxWidth: 900 }}>
        <h1 style={{ fontSize: 'var(--text-2xl)', marginBottom: 'var(--space-6)' }}>Design system · Lane A</h1>

        <Section title="Button">
          <Button variant="primary">Seal &amp; Distribute</Button>
          <Button variant="ghost">Download container</Button>
          <Button variant="quiet">switch role</Button>
          <Button variant="ghost" disabled hint="start it with `python scripts/demo.py --serve`">
            Seal &amp; Distribute
          </Button>
        </Section>

        <Section title="Panel">
          <Panel style={{ width: 260 }}>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700 }}>Sealed</div>
            <div style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)', marginTop: 'var(--space-2)' }}>
              Nothing is written to the ledger until a recipient opens it.
            </div>
          </Panel>
          <Panel elevated style={{ width: 260 }}>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700 }}>Elevated</div>
            <div style={{ color: 'var(--ink-muted)', fontSize: 'var(--text-sm)', marginTop: 'var(--space-2)' }}>
              One considered shadow. No glass.
            </div>
          </Panel>
        </Section>

        <Section title="Chip">
          <Chip>UNCLASSIFIED</Chip>
          <Chip selectable>Lt Sharma · watch</Chip>
          <Chip selectable selected>
            Lt Sharma · selected
          </Chip>
        </Section>

        <Section title="Hash (click to copy)">
          <Hash value="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08" label="ledger root" />
          <Hash value="ML-DSA-65" />
        </Section>

        <Section title="Banner">
          <Banner tone="struct" style={{ maxWidth: 520 }}>
            The ledger head updates on poll; if a witness is down the seal step warns before you try.
          </Banner>
        </Section>

        <Section title="Honesty — PresentNotVerified">
          <PresentNotVerified />
          <span>
            leaf 7 <PresentNotVerified inline />
          </span>
        </Section>

        <Section title="Honesty — FailClosed (green guarantee, not an error)">
          <FailClosed reason="Quorum could not be met: 2 of 3 witnesses co-signed." />
        </Section>

        <Section title="Honesty — Caveat (all four kinds)">
          <div style={{ display: 'grid', gap: 'var(--space-3)', maxWidth: 640 }}>
            <Caveat kind="proves-key" />
            <Caveat kind="ranking" />
            <Caveat kind="text-domain" />
            <Caveat kind="simulated" />
          </div>
        </Section>

        <Section title="ClassificationBanner">
          <div style={{ width: '100%', border: '1px solid var(--hairline)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
            <ClassificationBanner level="SECRET" position="top" caveat="deal-team only" />
            <div style={{ padding: 'var(--space-5)', color: 'var(--ink-muted)' }}>document body…</div>
            <ClassificationBanner level="SECRET" position="bottom" />
          </div>
        </Section>

        <Section title="SceneFallback (lite / reduced-motion poster)">
          <div style={{ width: 420 }}>
            <SceneFallback name="Akṣaya Śṛṅkhala" />
          </div>
        </Section>
      </div>
    </div>
  )
}
