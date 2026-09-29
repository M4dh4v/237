# CLAUDE.md — SĀKṢYA

Offline, defence-grade forensic-attribution instrument for the Indian Navy (WESEE), SIH problem SIH26237.
One line: *give the same secret file to many officers, every copy reads like an ordinary copy but quietly knows who opened it, and the record of who-opened-what is held by many witnesses so no single admin can rewrite it.*

## Read these before working
- `SAKSHYA-MASTER-DESIGN-PLAN.md` — the design bible (every screen, every 3D moment, the copy, the honesty rules). Authoritative.
- `SAKSHYA-FRONTEND-PLAYBOOK.md` — how we build it (themes, anti-slop rules, workflow, the 3 lanes, prompts).
- `web/src/design-system/contract.md` — the FROZEN shared interface (tokens, api methods, component props). Do not change without updating all lanes.

## Golden rules (do not violate)
1. **Do not touch the model's real working.** No changes to `logfirst/crypto/`, `logfirst/ledger/`, `logfirst/witness/`, `logfirst/watermark/`, `logfirst/forensics/`, or `verifier/`. Backend work is **thin glue only** — new adapter routes in `logfirst/authority/` that feed existing pipeline functions. Never add crypto, never change what/when gets committed. Full do-not-touch list in the design plan §13.
2. **Honesty rails are sacred.** present-not-verified (never fake "verified"), fail-closed-as-green-guarantee, the caveat system, two separated confidences, truthful ledger/watermark framing. See the `sakshya-honesty` skill. A judge trusts the tool that discloses its own limits.
3. **Air-gapped.** Zero external network calls in the frontend. Only origin is `127.0.0.1:8443`. Vendor every dep, font, texture, model. No CDN, no Google Fonts. Verify by building + disconnecting.
4. **Anti-slop.** This is a sonar console, not a SaaS template. No purple gradient washes, no glassmorphism-everywhere, no 3-card grids, no hype copy. One accent per screen. See the `sakshya-design` skill.
5. **3D only where it explains something**, ~60fps on a weak laptop, every scene ships a static fallback. See the `sakshya-3d` skill.
6. **Never commit. The human commits.** Do not run `git commit` (or `git push`). When work is ready to commit, stage nothing on your own authority — instead tell the human it's ready and let them make the commit. Do not add yourself as an author or co-author; no `Co-Authored-By` trailer, no AI attribution in any commit.

## Stack
React 18 + Vite 5. Adding: `@react-three/fiber`, `@react-three/drei`, `three`, `lenis`, `framer-motion`. Retiring `cytoscape` (ledger becomes the R3F WitnessRing). Backend: Python (`logfirst/`, run with `python scripts/demo.py --serve`).

## Structure
- `web/src/design-system/` — tokens.css, contract.md, primitives. **Lane A owns.**
- `web/src/scenes/` — R3F scenes + `*.static.jsx` fallbacks. **Lane A owns.**
- `web/src/components/` — shared honesty layer (StatusStrip, FailClosed, PresentNotVerified, Caveat, ClassificationBanner) + WitnessRing at 3 scales. **Lane A owns.**
- `web/src/dashboards/` — Dvārapāla (sender), Sūchī (recipient), Anveṣaṇa (investigator), Pramāṇapatra (certificate). **Lane B owns.**
- `web/src/api.js` — existing contract (ApiError, isFailClosed, isUnreachable) + new glue methods. **Lane C owns.**
- `logfirst/authority/` — existing ~22 routes + new glue endpoints. **Lane C owns.**

## Lanes (run in parallel git worktrees, never touch each other's files)
- **Lane A** = design system + landing + shared 3D scenes + shared components.
- **Lane B** = the 3 dashboards + certificate (consumes A's frozen components).
- **Lane C** = backend glue endpoints + api.js methods.
Freeze `contract.md` on `main` first; then branch the three worktrees.

## Conventions
- Never hardcode hex — use the CSS variables in `tokens.css`.
- Hashes/keys/IDs always in `--font-mono`.
- Every async surface handles loading (purposeful, shows the pipeline step names — never a bare spinner), error (with retry), and a meaningful empty state.
- Reuse existing `web/src/api.js` error shapes; new endpoints fail closed with the same shape.

## Verify before "done"
`cd web && npm run build` passes; disconnect network + reload (no 404/hang); screenshot via Playwright MCP and look at it; count anti-slop tells (2+ = revise). Backend: `python -m pytest` still green (do-not-touch modules unchanged).
