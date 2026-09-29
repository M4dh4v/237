/**
 * Pravāha scene — the landing's ONE continuous R3F canvas (design plan §6). A
 * single scroll-progress value (0→1, from Lenis via a ref) drives the whole
 * journey; the camera flows, it never cuts. One heavy canvas, code-split and
 * mounted only on the landing route. Reduced-motion / lite render the static
 * poster stack instead (Pravaha.jsx guards that — this file never mounts then).
 *
 * The through-line is a single sheet of paper, on screen the whole way down.
 * Stations assemble as their scroll band arrives and dissolve as it leaves:
 *   crowd (identical copies) · gate (record-first, key-second) · witness ring
 *   (many hold the same book, tamper quarantined) · trace (one leaf lit).
 *
 * Performance (sakshya-3d): crowd + ledger blocks are InstancedMesh; unlit
 * meshBasicMaterial (no shadows, no lights); dpr capped 1.5; < ~20 draw calls.
 * The accent (ice) is spent once at a time — the sealed block, then the traced
 * leaf — never two glows at once.
 */
import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Line } from '@react-three/drei'
import * as THREE from 'three'

function token(name, fallback) {
  if (typeof window === 'undefined') return fallback
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}

// 0 before a, ramps 0→1 across [a,b], 1 after b
const band = (p, a, b) => THREE.MathUtils.clamp((p - a) / (b - a), 0, 1)
// 0 at edges, 1 in the middle of [a,b] — a "present then gone" beat
const pulse = (p, a, b) => {
  const t = band(p, a, b)
  return Math.sin(t * Math.PI)
}

const CROWD = 50
const BLOCKS = 6

export default function PravahaScene({ progressRef }) {
  return (
    <Canvas
      dpr={[1, 1.5]}
      camera={{ position: [0, 0, 6], fov: 45 }}
      gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
      style={{ position: 'fixed', inset: 0, zIndex: 0 }}
    >
      <Scene progressRef={progressRef} />
    </Canvas>
  )
}

function Scene({ progressRef }) {
  const colors = useMemo(
    () => ({
      ink: new THREE.Color(token('--ink-faint', '#4A5563')),
      paper: new THREE.Color(token('--ink-muted', '#7D8896')),
      accent: new THREE.Color(token('--accent', '#7DF9FF')),
      struct: new THREE.Color(token('--struct-1', '#3D5AFE')),
      struct2: new THREE.Color(token('--struct-2', '#22D3EE')),
      alert: new THREE.Color(token('--alert', '#FF5470')),
    }),
    [],
  )

  const sheet = useRef()
  const crowd = useRef()
  const gateL = useRef()
  const gateR = useRef()
  const sealBlock = useRef()
  const ring = useRef()
  const blocks = useRef()
  const nodePts = useMemo(() => {
    const w = 5
    return Array.from({ length: w }, (_, i) => {
      const a = (i / w) * Math.PI * 2 - Math.PI / 2
      return [Math.cos(a) * 1.9, Math.sin(a) * 1.9, 0]
    })
  }, [])

  const dummy = useMemo(() => new THREE.Object3D(), [])

  useFrame(({ camera, clock }) => {
    const p = progressRef.current || 0
    const t = clock.elapsedTime

    // camera flows down and slightly in as the story advances (never cuts)
    camera.position.y = -p * 1.4
    camera.position.z = 6 - band(p, 0, 1) * 1.2
    camera.lookAt(0, camera.position.y, 0)

    // through-line sheet: breathes at the hook, drifts left into the gate,
    // then recedes for good as the ring takes over (never sits behind the
    // final proof/Darśana text)
    if (sheet.current) {
      const s = sheet.current
      const intoGate = band(p, 0.3, 0.46)
      const gone = band(p, 0.5, 0.62)
      // at the hook the sheet sits low so the SĀKṢYA wordmark stays clean;
      // it rises to centre as the journey starts
      const hookDrop = (1 - band(p, 0.0, 0.12)) * 0.9
      s.position.set(-intoGate * 1.2, -p * 1.4 - hookDrop + Math.sin(t * 0.6) * 0.04, 0.2)
      s.rotation.y = Math.sin(t * 0.4) * 0.15 + intoGate * 0.3
      s.scale.setScalar(1 - gone * 0.5)
      s.material.opacity = 0.5 * (1 - gone)
      s.visible = s.material.opacity > 0.01
    }

    // crowd of identical copies — present only at the problem station, then
    // gone (no stray instances littering the later stations)
    if (crowd.current) {
      const vis = band(p, 0.06, 0.22) * (1 - band(p, 0.24, 0.34))
      const leaker = Math.floor((0.5 + 0.5 * Math.sin(t * 1.3)) * CROWD) // wanders
      for (let i = 0; i < CROWD; i++) {
        const col = Math.floor(i / 5) - 5
        const row = (i % 5) - 2
        dummy.position.set(col * 0.62, -p * 1.4 + row * 0.5, -2 - Math.abs(col) * 0.15)
        dummy.rotation.set(0, 0, 0)
        dummy.scale.setScalar(vis * 0.34)
        dummy.updateMatrix()
        crowd.current.setMatrixAt(i, dummy.matrix)
        // one copy pulses red for a heartbeat — you cannot tell which
        const isLeaker = i === leaker && vis > 0.5 && Math.sin(t * 3) > 0.6
        crowd.current.setColorAt(i, isLeaker ? colors.alert : colors.paper)
      }
      crowd.current.instanceMatrix.needsUpdate = true
      if (crowd.current.instanceColor) crowd.current.instanceColor.needsUpdate = true
      crowd.current.visible = vis > 0.01
    }

    // the gate — two light bars; opens (parts) only after the seal beat
    const gateOn = band(p, 0.3, 0.5) * (1 - band(p, 0.5, 0.6))
    const opened = band(p, 0.42, 0.5) // record is written by 0.42, THEN it opens
    if (gateL.current && gateR.current) {
      const y = -p * 1.4
      gateL.current.position.set(-0.5 - opened * 0.6, y, 0)
      gateR.current.position.set(0.5 + opened * 0.6, y, 0)
      gateL.current.material.opacity = gateOn
      gateR.current.material.opacity = gateOn
      gateL.current.visible = gateR.current.visible = gateOn > 0.01
    }

    // the seal beat: a block flies SIDEWAYS into the ledger (left) and goes
    // accent BEFORE the gate opens — record first, key second
    if (sealBlock.current) {
      const fly = band(p, 0.32, 0.42)
      const on = pulse(p, 0.3, 0.52)
      sealBlock.current.position.set(-fly * 2.4, -p * 1.4 + 0.1, 0.3)
      sealBlock.current.material.opacity = on
      sealBlock.current.material.color.copy(fly > 0.9 ? colors.accent : colors.struct2)
      sealBlock.current.visible = on > 0.01
    }

    // the witness ring — many hold the same chain; one node is tampered and
    // quarantined (reddens) at the beat
    const ringOn = band(p, 0.5, 0.62) * (1 - band(p, 0.72, 0.82))
    if (ring.current) {
      ring.current.position.y = -p * 1.4
      ring.current.rotation.y = t * 0.15
      ring.current.visible = ringOn > 0.01
      ring.current.scale.setScalar(0.8 + ringOn * 0.2)
      ring.current.traverse((o) => {
        if (o.material && o.material.transparent) o.material.opacity = ringOn * (o.userData.base ?? 1)
      })
    }
    if (blocks.current) {
      const traced = band(p, 0.82, 0.95) // one leaf lit gold at the trace
      for (let i = 0; i < BLOCKS; i++) {
        const a = (i / BLOCKS) * Math.PI * 2
        dummy.position.set(Math.cos(a) * 0.5, Math.sin(a) * 0.5, 0)
        dummy.scale.setScalar(0.18)
        dummy.rotation.set(0, 0, 0)
        dummy.updateMatrix()
        blocks.current.setMatrixAt(i, dummy.matrix)
        const isTraced = traced > 0.5 && i === 2
        blocks.current.setColorAt(i, isTraced ? colors.accent : colors.ink)
      }
      blocks.current.instanceMatrix.needsUpdate = true
      if (blocks.current.instanceColor) blocks.current.instanceColor.needsUpdate = true
    }
  })

  const tampered = 3 // the quarantined witness at the tamper beat

  return (
    <group>
      {/* through-line: one sheet of paper */}
      <mesh ref={sheet}>
        <planeGeometry args={[1.3, 1.7]} />
        <meshBasicMaterial color={colors.paper} transparent opacity={0.9} side={THREE.DoubleSide} />
      </mesh>

      {/* the crowd of identical copies (instanced, one draw call) */}
      <instancedMesh ref={crowd} args={[undefined, undefined, CROWD]} visible={false}>
        <planeGeometry args={[0.5, 0.66]} />
        <meshBasicMaterial transparent opacity={0.8} side={THREE.DoubleSide} toneMapped={false} />
      </instancedMesh>

      {/* the gate — two vertical light bars */}
      <mesh ref={gateL} visible={false}>
        <boxGeometry args={[0.08, 2.4, 0.08]} />
        <meshBasicMaterial color={colors.struct} transparent opacity={0} toneMapped={false} />
      </mesh>
      <mesh ref={gateR} visible={false}>
        <boxGeometry args={[0.08, 2.4, 0.08]} />
        <meshBasicMaterial color={colors.struct} transparent opacity={0} toneMapped={false} />
      </mesh>

      {/* the block that flies to the ledger and locks in accent */}
      <mesh ref={sealBlock} visible={false}>
        <boxGeometry args={[0.32, 0.24, 0.18]} />
        <meshBasicMaterial transparent opacity={0} toneMapped={false} />
      </mesh>

      {/* the witness ring: nodes + shared chain + links */}
      <group ref={ring} visible={false}>
        <instancedMesh ref={blocks} args={[undefined, undefined, BLOCKS]}>
          <boxGeometry args={[1, 0.7, 0.5]} />
          <meshBasicMaterial transparent opacity={1} toneMapped={false} />
        </instancedMesh>
        {nodePts.map((pt, i) => (
          <mesh key={i} position={pt} userData={{ base: 1 }}>
            <octahedronGeometry args={[0.18, 0]} />
            <meshBasicMaterial
              color={i === tampered ? colors.alert : colors.struct}
              transparent
              opacity={1}
              toneMapped={false}
            />
          </mesh>
        ))}
        {nodePts.map((pt, i) => (
          <Line
            key={`e${i}`}
            points={[pt, nodePts[(i + 1) % nodePts.length]]}
            color={i === tampered || (i + 1) % nodePts.length === tampered ? '#FF5470' : token('--struct-2', '#22D3EE')}
            lineWidth={1}
            transparent
            opacity={0.5}
          />
        ))}
      </group>
    </group>
  )
}
