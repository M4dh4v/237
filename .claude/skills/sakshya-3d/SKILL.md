---
name: sakshya-3d
description: Use when building, editing, or debugging ANY 3D scene, WebGL, React Three Fiber (@react-three/fiber, @react-three/drei), Three.js, Lenis smooth-scroll, or GSAP/Framer-Motion scroll animation in the SĀKṢYA frontend. Enforces the offline performance budget, the mandatory static fallback for every scene, and the "3D only where it explains something" rule. Trigger on r3f/three/lenis/gsap/scroll/canvas/shader/mesh work.
---

# SĀKṢYA 3D & motion discipline

The demo machine is **not** a gaming rig and the app is **air-gapped**. Every 3D moment must hold ~60fps on a mid laptop with weak/no GPU, load zero external assets, and degrade to a still, beautiful poster if the machine struggles. 3D is used **only where it explains something** (the gate ordering, the many-witnesses idea, the trace from mark to name) — never as a spinning logo.

## The four signature 3D moments (the only heavy scenes)
1. **GateScene** (landing station 2 + recipient open): signature glyph flies *sideways* to the ledger, block goes accent-color, *then* the gate opens. The sequence IS the pitch — record first, key second.
2. **WitnessRing** (landing station 4 + shared ledger view, 3 scales): a ring of witness nodes each holding the same chain; a new block appears in all at once; tamper beat quarantines a bad node.
3. **SealScene** (sender step 4): one light-strand per recipient wraps a core into a crystal; ends *unopened* with the caption that nothing is written to the ledger until open.
4. **TraceScene** (landing station 5 + investigator result): marked words light up, assemble into the Abhijñāna token, fly to the ring, lock onto one leaf → name card.

## Hard performance budget (non-negotiable)
- **Instance everything repeated.** The 50-suspect crowd and the ledger blocks are `InstancedMesh` — never 50 separate meshes. Target < ~50 draw calls per scene.
- **Cap pixel ratio:** `dpr={[1, 1.5]}` on `<Canvas>`. Never render at full retina.
- **Lazy-mount per route.** The landing scene must NOT run while a dashboard is mounted. Use `React.lazy` + `<Suspense>`; dispose geometries/materials/textures on unmount (`useEffect` cleanup, `dispose()`).
- **Bake lighting.** Avoid real-time shadows; use baked/faked lighting, matcaps, or a single cheap light. No heavy post-processing stacks (at most one cheap bloom pass, guarded).
- **`frameloop="demand"`** for scenes that are static until interacted with (ledger inspect, seal receipt). Only the scroll-driven landing uses continuous loop.
- **Geometry/textures vendored & compressed.** Draco for any GLTF, KTX2/basis for textures, all shipped in `web/public/`. No CDN, no runtime fetch. Verify: build, disconnect network, load — nothing 404s or hangs.

## Every scene ships a static fallback — this is mandatory, not optional
For each `*.jsx` scene, create a `*.static.jsx` sibling: a composed still poster (CSS/SVG/pre-rendered image) with the **same copy**. Render the static version when:
- `window.matchMedia('(prefers-reduced-motion: reduce)').matches`, OR
- the user toggles **lite mode** in the status strip, OR
- WebGL context creation fails / is lost.
The narrative must read as six static frames. The pitch survives a weak GPU or a nervous laptop.

## Scroll (landing only)
- **Lenis** drives smooth scroll on the landing route ONLY (not dashboards). Sync it to the R3F render loop; drive scene progress from a single scroll-progress value (0→1), each station a range.
- Pick **one** scroll-animation approach and commit — Lenis + a scroll hook + Framer Motion for 2D reveals is the default; GSAP ScrollTrigger is the only acceptable alternative. **Never mix GSAP ScrollTrigger and Framer scroll on the same timeline.**
- Always provide a persistent "skip to app" affordance and honor reduced-motion by jumping straight to composed posters.

## Structure
- `web/src/scenes/` — GateScene, WitnessRing, SealScene, TraceScene, plus each `*.static.jsx`.
- Keep scene state out of global stores; pass progress/props down. Reuse the WitnessRing component at three scales (strip / widget / full) driven by props, so the recipient and investigator provably see the same object.

## Before declaring a scene done
1. Build, disconnect network, reload — confirm no external request, no 404.
2. Throttle CPU 4–6× in devtools; confirm it still moves acceptably or the fallback kicks in.
3. Screenshot via Playwright MCP and actually look at it — is the motion *explaining* something, or is it decoration? If decoration, cut it.
