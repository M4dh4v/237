# PROGRESS — Lane A

Read this + CLAUDE.md + `web/PLAN-lane-a.md` to resume with zero context loss.

## Done
### Legibility fix (last section) ✅ (build green)
- `PravahaScene.jsx`: crowd instances no longer ghost-reappear at the trace (removed the `band(0.74,0.82)*0.5` term) — no stray grey squares littering the final Darśana section. Through-line sheet now fades fully out after the ring (`opacity = 0.5*(1-gone)`, `visible` gated) instead of returning small behind the "Darśana" text.
- `Pravaha.jsx`: bumped the "'present', not 'verified'" caption from `--ink-faint` to `--ink-muted` for contrast.
- Screenshotted the bottom: final section reads clean on the dark bg, no bleed-through.

### Phase 1 — Design system finalised ✅ (build green, not yet committed)
- Retired cytoscape: deleted 11 orphaned pre-remodel components (ChainGraph, LedgerGraph, LedgerView, DistributeOpen, LeakCheck, OpenContainer, Users, TamperAct, RobustnessAct, ActRail, StatusBar) + `src/styles.css`. Removed `cytoscape` from package.json; `npm i` pruned it. Nothing live imported them (verified).
- `design-system/scale.css` — space (`--space-1..8`), type (`--text-xs..3xl`), shadow (`--shadow-1/2`, `--glow-accent`). Imported by tokens.css. Adds no hex.
- `design-system/primitives.jsx` + `primitives.css` — Button (primary/ghost/quiet, sm, disabled+hint), Panel (elevated/pad), Chip (selectable/selected), Banner (neutral notice), Hash (mono, middle-ellipsis, copy-on-click). Token-only.
- `design-system/index.js` barrel → Lane B imports `@/design-system`.
- `npm run build` passes (52 modules).

## Next
- Lane A phases 1–5 complete. Nothing pending on Lane A. (Waiting on the human to commit.)

### Phase 5 — Shell wiring ✅ (build green)
- `App.jsx`: dashboards (Dvārapāla/Sūchī/Anveṣaṇa) now `React.lazy` + per-route `<Suspense fallback={<SceneFallback/>}>`, matching the scene pattern — each dashboard is its own chunk (off the landing/main bundle) and one broken dashboard can't white-screen the app. Landing `/` + `*` already lazy-mount `Pravaha`; `/ledger` renders the real full-scale WitnessRing.
- Landing already carries the lite toggle (StatusStrip) + persistent "skip to app →"; verified the toggle flips the whole landing to the poster path (canvas unmounts, 6 static motifs render) and back.
- Verified the walk `/` → `/darsana` → `/dvarapala` (Authed shell strip + lite reachable, no crash).
- `index.html`: title was the stale pre-remodel "logfirst — distribute, open, leak check" → now "SĀKṢYA — evidence-grade forensic attribution".
- `npm run build` green (3.08s). Chunks: Pravaha 141kB, Line (three) 839kB code-split, dashboards each their own chunk.

## Gotchas (added)
- **Vite dep-optimizer can wedge with "more than one copy of React" / framer-motion `useContext` null.** Seen in dev when the optimizer re-runs mid-session and framer-motion holds a stale React ref (different `?v=` hash than react-dom). Not a code bug — prod build is unaffected. Fix: `rm -rf web/node_modules/.vite` and restart the dev server.
- **Dashboards fetch the Python backend** (`/demo/...`, `/ledger/head`) → `ECONNREFUSED 127.0.0.1:8443` in dev when the backend isn't running (`python scripts/demo.py --serve`). Expected; Lane B/C surfaces, not a landing issue.

### Phase 4 — Pravāha landing scroll journey ✅ (build green, screenshotted, not committed)
- `scenes/useLenisProgress.js` — Lenis smooth scroll, landing-only, one RAF loop, `destroy()` on unmount. Writes one 0→1 progress into a ref (no React re-render per frame); `enabled` flag so it never mounts on the poster path.
- `scenes/PravahaScene.jsx` — ONE persistent fixed R3F canvas, scroll-progress drives the whole journey (camera flows, never cuts). Through-line paper sheet + instanced crowd (50, one draw call) + gate bars + the seal beat (block flies SIDEWAYS to the ledger and goes accent BEFORE the gate opens — record first, key second) + witness ring (instanced blocks + nodes + drei lines, one node tampered → reddens + red edges = quarantine) + one leaf lit accent at the trace. Unlit `meshBasicMaterial`, `dpr={[1,1.5]}`, <~20 draw calls, colours from tokens. Accent spent once at a time (sealed block, then traced leaf).
- `scenes/Pravaha.jsx` — the landing: StatusStrip (offline, ledger 0, lite toggle, role switch), persistent skip-to-app, 7 stations (hook → problem → gate → mark → witnesses → trace → proof+Darśana doors), Framer `whileInView` reveals (text arrives with its scene). Copy verbatim-in-spirit from design plan §6. Certificate row says "present", never "verified". Ends by pouring into the three Darśana doors (sets role + navigates).
- `scenes/PravahaMotif.jsx` — still SVG motif per station for the poster path (lite / reduced-motion / no-WebGL); reuses WitnessRingStatic for the ring. Same copy → reads as static frames.
- `App.jsx` — `/` and `*` now lazy-mount `Pravaha` (removed the placeholder Landing + GateScene/Link imports).
- Hero (user feedback): big SĀKṢYA display wordmark (clamp to 240px) + Devanagari साक्ष्य (cyan) above it; dropped the "evidence, in Sanskrit" line. Sheet drops low at the hook so the wordmark stays clean.
- `npm run build` green (1006 modules; three lands in the code-split Line chunk, loaded only when a scene mounts — never on dashboards).

## Gotchas (added)
- **Devanagari font not vendored.** साक्ष्य uses a `'Noto Sans Devanagari', 'Nirmala UI', system-ui` stack — renders in the preview browser (has Noto), but the air-gapped demo machine may lack a Devanagari font → tofu. To guarantee it, drop a `Noto Sans Devanagari` woff2 into `web/public/fonts/` + an `@font-face` in fonts.css (needs the file; can't fetch offline here).


### Phase 3 — WitnessRing R3F ✅ (build green, screenshotted, not committed)
- `components/WitnessRing.jsx` — ONE R3F component, 3 scales (strip 48 / widget 220 / full). Ledger blocks are `InstancedMesh` (one draw call, `BLOCK_CAP=24`); witness nodes are few, so individual meshes; drei `<Line>` for spokes + ring. `dpr={[1,1.5]}`, `frameloop="demand"` (highlight/tamper are React state, renders once per change, idles 0% CPU). `meshBasicMaterial` (unlit, no shadows). Colours read from tokens.css at runtime (`token()`), zero hardcoded hex. drei `OrbitControls` (no pan/zoom) only when `full + interactive`. Removed the dead `useFrame` idle-rotation (never ticks in demand mode) — the ring is a still, inspectable instrument; drag to orient.
- Tamper beat: click a witness node → it reddens (`--alert`) + its spoke dims — the "no single admin rewrites history" quarantine, honest.
- `highlightLeaf` → that instanced block turns `--accent` (the one focal point).
- `components/WitnessRing.static.jsx` (NEW) — SVG poster, same 3 scales, same idea, same honest caption ("N independent witnesses co-sign a shared, append-only ledger… no single admin can rewrite it"). Rendered on lite / prefers-reduced-motion / no-WebGL. Fixed invalid SVG `height="auto"` attribute (moved to CSS).
- Gallery `/_ds` gains a WitnessRing section (strip+widget+full+poster) for review.
- `npm run build` green (647 modules; three/fiber/drei now bundled — WitnessRingScene chunk 860kB is code-split + lazy per route, never loaded on the landing/dashboards until /ledger).


### Phase 2 — Real honesty components ✅ (build green, screenshotted, not committed)
- Restyled StatusStrip onto primitives (quiet Buttons; reserved-colour dot: green reachable / alert unreachable; quorum turns green when met). Props + copy frozen.
- PresentNotVerified / FailClosed / Caveat(×4) / ClassificationBanner / SceneFallback verified in a dev gallery. Honesty rails hold: PNV never green, FailClosed = green guarantee (not red), caveats verbatim, classification spends no reserved colour.
- Dev-only gallery at `/_ds` (`design-system/Gallery.jsx`), not linked in nav. Screenshotted every state; anti-slop tells = 0.
- Fixed PNV block wrap ("present, as received" now one line).

## Decisions
- Theme A. Accent `--accent #7DF9FF` once per screen. Scroll = Lenis + Framer, no GSAP. Static-first per scene.
- User approved deleting all 12 dead files + dropping cytoscape.

## Gotchas
- `npm install` cannot reach registry in sandbox (network denied) — deletions/prunes work offline, but adding a new dep would need the network allowed. No new deps planned.
- Do NOT commit — the human commits. Tell them when a phase is ready.
