// GateScene STUB (sakshya-3d §1). The real R3F scene — signature glyph flies
// sideways to the ledger, the block goes accent, THEN the gate opens (record
// first, key second) — is Lane A. Until then this is a placeholder that still
// honours lite mode by falling back to the static poster.
import { useLite } from '@/shell/context.jsx'
import GateStatic from './GateScene.static.jsx'

export default function GateScene(props) {
  const { lite } = useLite()
  if (lite) return <GateStatic {...props} />
  return (
    <div
      style={{
        display: 'grid',
        placeItems: 'center',
        minHeight: 240,
        border: '1px dashed var(--hairline)',
        borderRadius: 'var(--radius)',
        color: 'var(--ink-faint)',
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
      }}
    >
      GateScene · R3F scene is Lane A
    </div>
  )
}
