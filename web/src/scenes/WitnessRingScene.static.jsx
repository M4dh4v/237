import WitnessRing from '@/components/WitnessRing.jsx'

// Static poster for the witness ring — the same WitnessRing component, still.
export default function WitnessRingStatic({ data, ...props }) {
  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: 260 }}>
      <WitnessRing scale="full" data={data} interactive={false} {...props} />
    </div>
  )
}
