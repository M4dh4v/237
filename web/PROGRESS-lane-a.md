# PROGRESS — Lane A

Read this + CLAUDE.md + `web/PLAN-lane-a.md` to resume with zero context loss.

## Done
### Phase 1 — Design system finalised ✅ (build green, not yet committed)
- Retired cytoscape: deleted 11 orphaned pre-remodel components (ChainGraph, LedgerGraph, LedgerView, DistributeOpen, LeakCheck, OpenContainer, Users, TamperAct, RobustnessAct, ActRail, StatusBar) + `src/styles.css`. Removed `cytoscape` from package.json; `npm i` pruned it. Nothing live imported them (verified).
- `design-system/scale.css` — space (`--space-1..8`), type (`--text-xs..3xl`), shadow (`--shadow-1/2`, `--glow-accent`). Imported by tokens.css. Adds no hex.
- `design-system/primitives.jsx` + `primitives.css` — Button (primary/ghost/quiet, sm, disabled+hint), Panel (elevated/pad), Chip (selectable/selected), Banner (neutral notice), Hash (mono, middle-ellipsis, copy-on-click). Token-only.
- `design-system/index.js` barrel → Lane B imports `@/design-system`.
- `npm run build` passes (52 modules).

## Next
- Phase 3 (WitnessRing R3F), Phase 4 (Pravaha landing), Phase 5 (shell wiring).

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
