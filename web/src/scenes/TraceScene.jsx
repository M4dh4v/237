// TraceScene STUB (sakshya-3d §4). The real scene: marked words light up,
// assemble into the Abhijñāna token, fly to the ring, and lock onto one leaf ->
// name card. Lane A builds the R3F.
import { useLite } from '@/shell/context.jsx'
import TraceStatic from './TraceScene.static.jsx'

export default function TraceScene(props) {
  const { lite } = useLite()
  if (lite) return <TraceStatic {...props} />
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
      TraceScene · R3F scene is Lane A
    </div>
  )
}
