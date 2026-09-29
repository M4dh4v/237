/**
 * WitnessRing — ONE R3F component at three scales (contract §3, design plan §10,
 * sakshya-3d §2). strip (sender pulse) · widget (recipient open) · full (shared
 * ledger / investigator). Same data, same object: the recipient and the
 * investigator provably see the SAME ring, so it is literally one component.
 *
 * Honest framing (sakshya-honesty §6): many independent witnesses co-sign a
 * shared, append-only, post-quantum ledger — like a private network where
 * everyone holds the book. Never "blockchain / mining / coin".
 *
 * Performance (sakshya-3d): ledger blocks are InstancedMesh; dpr capped at 1.5;
 * frameloop="demand" (every change is React-driven, so it renders on demand and
 * idles at 0% CPU); geometries/materials disposed on unmount by R3F. Falls back
 * to the static poster on lite mode, prefers-reduced-motion, or no WebGL.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Line } from '@react-three/drei'
import * as THREE from 'three'
import { useLite } from '@/shell/context.jsx'
import WitnessRingStatic from './WitnessRing.static.jsx'

const SIZES = { strip: 48, widget: 220, full: 480 }
const BLOCK_CAP = 24 // instanced; never one mesh per leaf

// read a themed colour from tokens.css so nothing is hardcoded here either
function token(name, fallback) {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

function hasWebGL() {
  if (typeof window === 'undefined') return false
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl') || c.getContext('experimental-webgl'))
  } catch {
    return false
  }
}

export default function WitnessRing({
  scale = 'full',
  data,
  highlightLeaf,
  onInspect,
  interactive = false,
}) {
  const { lite } = useLite()
  const [webgl] = useState(hasWebGL)
  const reduced =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  const leaves = Array.isArray(data)
    ? data.length
    : data?.leaves ?? data?.entries?.length ?? 0
  const witnesses = data?.witnesses ?? data?.quorum?.need ?? 3
  const size = SIZES[scale] ?? SIZES.full

  // Poster path: identical copy, no WebGL. The pitch survives a weak GPU.
  if (lite || reduced || !webgl) {
    return (
      <WitnessRingStatic
        scale={scale}
        leaves={leaves}
        witnesses={witnesses}
        highlightLeaf={highlightLeaf}
      />
    )
  }

  const clickable = interactive && typeof onInspect === 'function'
  const isFull = scale === 'full'

  return (
    <div
      style={{
        width: isFull ? '100%' : size,
        height: isFull ? 'min(60vh, 520px)' : size,
        maxWidth: isFull ? undefined : size,
        position: 'relative',
      }}
      aria-label={`witness ring (${scale}) — ${leaves} leaves, ${witnesses} witnesses`}
    >
      <Canvas
        dpr={[1, 1.5]}
        frameloop="demand"
        camera={{ position: [0, 1.6, 5.2], fov: 42 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      >
        <RingScene
          leaves={leaves}
          witnesses={witnesses}
          highlightLeaf={highlightLeaf}
          onInspect={clickable ? onInspect : undefined}
        />
        {isFull && interactive ? (
          <OrbitControls enablePan={false} enableZoom={false} minPolarAngle={0.9} maxPolarAngle={1.9} />
        ) : null}
      </Canvas>
    </div>
  )
}

/* ---- the scene ------------------------------------------------------- */

function RingScene({ leaves, witnesses, highlightLeaf, onInspect }) {
  const group = useRef()
  const blocksRef = useRef()

  const colors = useMemo(
    () => ({
      block: new THREE.Color(token('--ink-faint', '#4A5563')),
      accent: new THREE.Color(token('--accent', '#7DF9FF')),
      struct: new THREE.Color(token('--struct-2', '#22D3EE')),
      node: new THREE.Color(token('--struct-1', '#3D5AFE')),
      alert: new THREE.Color(token('--alert', '#FF5470')),
    }),
    [],
  )

  const shown = Math.max(1, Math.min(leaves || 1, BLOCK_CAP))
  const ringR = 2.4
  const nodePts = useMemo(() => {
    const pts = []
    for (let i = 0; i < witnesses; i++) {
      const a = (i / witnesses) * Math.PI * 2
      pts.push([Math.cos(a) * ringR, 0, Math.sin(a) * ringR])
    }
    return pts
  }, [witnesses])

  // one tamper node, quarantined — the "no single admin rewrites history" beat
  const [tampered, setTampered] = useState(-1)

  // place instanced ledger blocks in a short central stack (a chain head)
  useEffect(() => {
    const mesh = blocksRef.current
    if (!mesh) return
    const dummy = new THREE.Object3D()
    for (let i = 0; i < shown; i++) {
      const t = shown === 1 ? 0 : i / (shown - 1)
      dummy.position.set((t - 0.5) * 2.2, Math.sin(t * Math.PI) * 0.12, 0)
      dummy.rotation.set(0, 0, 0)
      dummy.scale.setScalar(0.26)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
      const isHi = highlightLeaf != null && Number(highlightLeaf) === i
      mesh.setColorAt(i, isHi ? colors.accent : colors.block)
    }
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }, [shown, highlightLeaf, colors])

  // Demand frameloop: no idle animation loop — the ring is a still, inspectable
  // instrument. Highlight/tamper are React state, so each change renders once
  // and the canvas idles at 0% CPU. Drag (OrbitControls, full+interactive) to
  // orient; drei invalidates on drag.

  return (
    <group ref={group}>
      {/* the shared chain — instanced, one draw call for all blocks */}
      <instancedMesh
        ref={blocksRef}
        args={[undefined, undefined, shown]}
        onClick={onInspect ? (e) => { e.stopPropagation(); onInspect(e.instanceId ?? null) } : undefined}
      >
        <boxGeometry args={[1, 0.7, 0.5]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>

      {/* witness nodes — few (3–7), so individual meshes, not instanced */}
      {nodePts.map((p, i) => (
        <mesh
          key={i}
          position={p}
          onClick={() => setTampered((t) => (t === i ? -1 : i))}
        >
          <octahedronGeometry args={[0.22, 0]} />
          <meshBasicMaterial
            toneMapped={false}
            color={i === tampered ? colors.alert : colors.node}
            transparent
            opacity={i === tampered ? 0.5 : 1}
          />
        </mesh>
      ))}

      {/* the shared book: each witness linked to the chain head + the ring */}
      {nodePts.map((p, i) => (
        <Line
          key={`spoke-${i}`}
          points={[p, [0, 0, 0]]}
          color={i === tampered ? '#FF5470' : token('--struct-2', '#22D3EE')}
          lineWidth={1}
          transparent
          opacity={i === tampered ? 0.4 : 0.5}
        />
      ))}
      <Line
        points={[...nodePts, nodePts[0]]}
        color={token('--struct-1', '#3D5AFE')}
        lineWidth={1}
        transparent
        opacity={0.35}
      />
    </group>
  )
}
