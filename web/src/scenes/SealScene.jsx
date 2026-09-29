// SealScene STUB (sakshya-3d §3). The real scene: one light-strand per recipient
// wraps a core into a crystal, ending UNOPENED with the caption that nothing is
// written to the ledger until open. Lane A builds the R3F.
import { useLite } from '@/shell/context.jsx'
import SealStatic from './SealScene.static.jsx'

export default function SealScene(props) {
  const { lite } = useLite()
  if (lite) return <SealStatic {...props} />
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
      SealScene · R3F scene is Lane A
    </div>
  )
}
