# PLAN — Lane A (Foundation, shared components, scenes, landing)

Owner: Lane A. Scope: `web/src/design-system/`, `web/src/scenes/`, `web/src/components/`, the app shell (`App.jsx`, router, role context, StatusStrip mount, Suspense), and the landing route.
Do NOT touch: `web/src/dashboards/`, `web/src/api.js`, `logfirst/`. `contract.md` is frozen.

Theme: **A — Abyssal Sonar** (already in `tokens.css`). Accent `--accent #7DF9FF` (ice), used **once per screen**.

---

## 0. Where P0 left us (verified by reading the tree)

- `tokens.css` + `fonts.css` are complete and correct; fonts vendored in `web/public/fonts/` (7 woff2). No CDN. Good.
- Shell exists: `App.jsx` (router + Landing + Darsana + Ledger placeholders), `shell/context.jsx` (RoleContext + Lite context, seeds lite from prefers-reduced-motion), `shell.css` (base only).
- Shared components exist as **stubs** with frozen props: StatusStrip, PresentNotVerified, FailClosed, Caveat, ClassificationBanner, WitnessRing, SceneFallback + `index.js` barrel. Copy in Caveat/PNV/FailClosed is already the honesty contract — keep the words, restyle only.
- Scenes exist as **stubs**: GateScene, WitnessRingScene, SealScene, TraceScene, each with a `.static.jsx` sibling (placeholder posters). GateScene already honours lite mode.
- Deps installed: `@react-three/fiber@8`, `@react-three/drei@9`, `three@0.169`, `lenis@1.3`, `framer-motion@11`, plus `cytoscape@3` (to retire).
- **Dead code from the pre-remodel app** still lives in `components/`: ChainGraph, LedgerGraph, LedgerView, DistributeOpen, LeakCheck, OpenContainer, Users, TamperAct, RobustnessAct, ActRail, StatusBar — and `src/styles.css`. Nothing in App/dashboards/main imports them (verified: they only import each other). ChainGraph is the sole cytoscape user.

---

## Decisions locked (call these out if you disagree)

1. **Delete the orphaned pre-remodel components + `styles.css`, then drop the `cytoscape` dep.** They are dead (no live importer), and "retire cytoscape" is in the prompt. Deletion over dead weight. — *needs your ok before I remove 12 files.*
2. **Scroll approach: Lenis + a single scroll-progress hook + Framer Motion for 2D reveals.** No GSAP. One continuous `progress` 0→1; each station a sub-range. (sakshya-3d rule: pick one, commit.)
3. **Static-first.** Build each scene's `.static.jsx` poster as a real composed frame *first* (it is the demo-safe floor), then layer the live R3F on top. Lite mode / reduced-motion / WebGL-fail all render the identical poster with identical copy.
4. **One R3F `<Canvas>` for the whole landing**, driven by the shared progress value — the camera flows, never cuts (design plan §6). Dashboards get their own small canvases (WitnessRing widget/strip) mounted only on their route.
5. **A `primitives.jsx` + `primitives.css` in `design-system/`** for Button, Panel, Chip, Banner, Hash. Small, token-only, no new dep. Banner here is the generic panel-banner; the honesty `ClassificationBanner` stays its own component.

---

## Build order (commit after each phase; screenshot + iterate twice per surface)

### Phase 1 — Design system finalised
- `design-system/primitives.jsx` + `primitives.css`:
  - `Button` (variants: `primary` = accent outline+glow used once, `ghost`, `quiet`; sizes sm/md; disabled state carries the backend-hint pattern).
  - `Panel` (solid `--bg-panel`, 1px `--hairline`, 4px radius, one considered shadow token — no glass, no blur).
  - `Chip` (quiet by default; `selected` gains accent rim — for recipient cards / classification later, exported for Lane B via `@/design-system`).
  - `Banner` (generic inline notice; neutral).
  - `Hash` (mono, `--font-mono`, ellipsis-middle for long roots/fingerprints, copy-on-click, `title` = full value).
- Type/space/shadow scale as CSS custom props appended to `shell.css` scope or a `scale.css` (`--space-1..6`, `--text-xs..3xl`, `--shadow-1`). Reads from existing tokens; adds no hex.
- Retire cytoscape (decision 1): delete dead components + `styles.css`, remove `cytoscape` from package.json, `npm i` to update lock, `npm run build` green.
- **Gate:** build passes; anti-slop self-check (0 tells on primitives page).

### Phase 2 — Real honesty components (restyle stubs to primitives; props + copy frozen)
- `StatusStrip`: keep props; render with primitives; live-polling-ready (already prop-driven — no fetching here). Add the **lite toggle** and **switch role** as proper `Button quiet`. Offline dot uses `--verified` only when truly offline-reachable, `--alert` on unreachable (reserved-colour rule). Include witnesses-up + quorum `m/n`.
- `PresentNotVerified`: calm chip, never green, points at `verifier/`. inline + block forms.
- `FailClosed`: green-framed guarantee (reserved green legitimately — a demonstrated guarantee is a checked outcome), reads an `ApiError` or string. Not a red box.
- `Caveat`: four kinds (`proves-key`, `ranking`, `text-domain`, `simulated`), copy verbatim from stub. Style as a quiet left-ruled note.
- `ClassificationBanner`: thin banded strip, top/bottom, neutral (no reserved colour spent), optional handling caveat.
- `SceneFallback`: shared frame; each scene's poster plugs in.
- **Gate:** a components gallery route (dev-only, `/_ds`, not linked in prod nav) or a temporary section on `/` to screenshot all states. Honesty rails check: no fake "verified", fail-closed green, PNV present.

### Phase 3 — Real WitnessRing (ONE R3F component, three scales) + static fallback
- `components/WitnessRing.jsx` becomes R3F-backed but keeps the **exact frozen props** (`scale`, `data`, `highlightLeaf`, `onInspect`, `interactive`).
  - `strip` (≈48px, sender pulse): condensed chain-head glyphs, live-poll-friendly, `frameloop="demand"` unless animating a new leaf.
  - `widget` (≈220px, recipient open): small ring, head counter ticks on new leaf, co-signatures land.
  - `full` (≈480px+, ledger/investigator): full ring — **InstancedMesh** for blocks and witness nodes, additive glow (no post stack, or one guarded cheap bloom), thin sync light-lines, tamper beat (a node reddens + is quarantined) when `interactive`, `highlightLeaf` lights one leaf + its Merkle branch, `onInspect(leafIndex)` on click. `dpr={[1,1.5]}`, dispose geometries/materials on unmount, `frameloop="demand"` (renders on interaction/new data).
- `WitnessRing.static.jsx`: composed SVG/CSS ring poster at each scale with identical caption. Used on lite/reduced-motion/WebGL-fail. (WitnessRing lives in `components/`; its static sibling lives beside it or in `scenes/` — put it in `components/` next to the component.)
- Honest framing per skill: caption "many independent witnesses co-sign a shared, append-only, post-quantum ledger — like a private network where everyone holds the book." Never "blockchain/mining/coin".
- **Gate:** build; disconnect network + reload (no fetch/404); CPU-throttle 6× → still moves or falls back; ≤~50 draw calls (instanced). Screenshot full ring.

### Phase 4 — The landing scroll journey Pravāha (§6, stations 0–6)
- `scenes/Pravaha.jsx` — one `<Canvas>` + Lenis + `useScrollProgress` (0→1). The single **paper sheet** is the through-line mesh, present the whole way.
- Stations as progress sub-ranges, camera flows never cuts:
  - **0 Hook** — paper breathing, headline resolves "Every copy looks the same. Every copy knows who opened it.", `SĀKṢYA · evidence, in Sanskrit`, down-chevron, status strip already visible, 50 faint ghost copies fanned behind.
  - **1 Problem** — ghosts become a crowd (InstancedMesh, 50), one pulses red a heartbeat then hides. Copy: "One file. Fifty readers. It leaks. Every copy is identical, so everyone is equally guilty, and no one can be named."
  - **2 Gate (GateScene reused)** — signature glyph flies **sideways** to the ledger stack, block goes **accent** (the one accent moment), **then** gate opens, key flows in. Copy: "Dvārapāla, the gate. The key is never released until the recipient's own post-quantum signature is written to the ledger. There is no opening without a trace."
  - **3 Mark (Guptamudrā)** — zoom into legible words; a light thread from the block; scattered words shimmer/change (synonym), faint accent underline fades; pull back to Alice/Bob copies with differing marked words. Copy: "…Two people open the same file and receive two different hidden marks. It reads as an ordinary copy. It is not." (never "pixel-identical").
  - **4 Witnesses (WitnessRing reused, scale full)** — stack lifts, multiplies into a ring; new block appears in all at once; tamper beat quarantines a bad node. Copy: the §6 witness paragraph.
  - **5 Trace (TraceScene reused)** — leaked skewed page, magnifier reveals marked words → Abhijñāna token → flies to ring → locks one leaf → name card; 49 of 50 dim to grey, one stays accent. Copy: "Anveṣaṇa, the investigation…"
  - **6 Proof + door** — name card seals into Pramāṇapatra with wax-press + row of green **present** checks (present, not verified). Final line + three doors = the Darśana CTA. Landing pours into the app.
- Each station also authored as a `.static.jsx` poster (GateScene/SealScene/TraceScene/WitnessRing already have static siblings — fill them in). Reduced-motion / lite renders the six posters with identical copy (a `Pravaha.static.jsx` stitches them into a scrollable static story).
- Persistent **skip-to-app** top-right (already in shell — make it always-present on `/`).
- **Gate:** the one-line test — strip the words, does it read as a defence instrument not a SaaS? Anti-slop count < 2. Screenshot at desktop width + with reduced-motion forced.

### Phase 5 — Shell wiring
- `App.jsx`: mount real `Pravaha` on `/`; ensure skip-to-app + lite toggle reachable on the landing (StatusStrip is dashboard-only today — add a minimal landing affordance for skip + lite, or mount a slim strip variant on `/`). Keep `<Suspense>` + `React.lazy` for `Pravaha` and `WitnessRingScene` so the landing scene never runs inside a dashboard.
- Lite-mode toggle in StatusStrip already wired to context; confirm it flips every scene to poster.
- `/ledger` route renders full-scale WitnessRing (real).
- **Gate:** full build; air-gap reload; walk `/` → `/darsana` → a dashboard (placeholder) with strip; screenshots.

---

## Cross-cutting rules I will hold every phase
- No hardcoded hex — CSS vars only. Hashes/keys/IDs in `--font-mono`.
- One accent per screen. Structure gradient (indigo→cyan) for lines/thinking only, never a hero wash.
- No glassmorphism default, no 3-card grid, no rounded-2xl-everything, no gradient text, no hype copy, no pure-white-on-black, no uniform fade-up motion.
- Every 3D scene: instanced repeats, `dpr={[1,1.5]}`, dispose on unmount, `frameloop="demand"` where static-until-touched, static fallback with identical copy, zero external fetch.
- Honesty: present-not-verified everywhere proofs show; fail-closed = green guarantee; two confidences never merged (relevant when Lane B consumes); reserved colours never decorative.
- After each surface: `npm run build`, Playwright screenshot, compare to design plan station-by-station, iterate twice, then show you. Update `web/PROGRESS-lane-a.md`.

## Risks / open
- Landing R3F is the big lift; if it endangers the deadline, the static posters are the demo floor and live 3D is the upgrade (playbook §9 sequencing).
- Decision 1 (deleting 12 dead files) — confirm before I remove.
- I will not commit; I'll tell you when a phase is ready and you commit.
