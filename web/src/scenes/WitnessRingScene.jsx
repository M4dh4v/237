// WitnessRingScene STUB (sakshya-3d §2). The real scene mounts the shared
// WitnessRing component at `full` scale: a ring of witness nodes each holding
// the same chain, a new block appearing in all at once, the tamper beat. Lane A
// builds the R3F. This stub already uses the real WitnessRing component so the
// "same object at three scales" claim holds even now.
import { useLite } from '@/shell/context.jsx'
import WitnessRing from '@/components/WitnessRing.jsx'
import WitnessRingStatic from './WitnessRingScene.static.jsx'

export default function WitnessRingScene({ data, ...props }) {
  const { lite } = useLite()
  if (lite) return <WitnessRingStatic data={data} {...props} />
  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: 260 }}>
      <WitnessRing scale="full" data={data} {...props} />
    </div>
  )
}
