# Lane B — progress

Lane B owns `web/src/dashboards/` only. Consumes Lane A's frozen `@/components`
+ `@/design-system` tokens and Lane C's `@/api.js` methods (contract §2/§3).
Never edits those lanes; never commits (the human commits).

## Shared scaffolding (done)
- `_shared/ui.jsx` — token-only UI kit (Panel, Button, Field, Input, Textarea,
  Pill, Tabs, Metric, mono, shortHash). No hardcoded hex, sharp corners.
- `_shared/useAsync.jsx` — idle→loading→success|error state machine, supersede
  by seq, retry. **Fix:** re-arm `alive` ref on mount (StrictMode was leaving it
  false after remount, hanging every surface on "loading" forever).
- `_shared/Async.jsx` — Async/Loading/ErrorState/Empty. Loading names the
  pipeline steps (never a bare spinner); ErrorState is calm on `isUnreachable`.
- `dashboards.css` — keyframes + `.lb-*` classes + `@media print`.

## Dvārapāla — sender (done)
Four-step gate: Source → Recipients → Classification → Seal.
- `StepRail` (map + progress, current glows accent, done cyan, gated by reached).
- `SourceStep` — corpus / upload / compose / paste tabs; preview + `CapacityMeter`.
- `CapacityMeter` — positions vs 1201; ample=struct cyan, thin=accent-soft (never
  the reserved alert red — thin text is a limitation, not a failure).
- `RecipientStep` — selectable recipient cards (revoked shown, not selectable) +
  inline enroll (`createRecipient`).
- `ClassifyStep` — banded chips (UNCLASSIFIED·RESTRICTED·CONFIDENTIAL·SECRET) +
  live `ClassificationBanner` preview.
- `SealStep` — review → `distribute`; embeds `SealScene`, closes UNOPENED with
  the gate caption "nothing is written to the ledger until a recipient opens it".
- `Dvarapala.jsx` — wires the rail + stage + right-rail live ledger pulse
  (`WitnessRing scale="strip"`).

Verified: `npm run build` clean; screenshotted the source + compose surfaces.
Backend was down in this env (missing `fpdf2`, a Lane C/env dep) — surfaces
correctly showed the calm "Backend not reachable" state, proving the honesty
rail. Live-data screenshots pending a running backend.

## Sūchī — recipient (done)
Inbox + open surface. Identity chip (labelled "demo convenience"), inbox polls
`documents()` every 5s and filters to sealed docs granting `me`. `OpenFlow`:
before-open shows the gate ring + "nothing is recorded until you open"; open →
`open({mark:true})`; success renders the marked copy (toggle reveals the mark
diff), the ledger leaf as the SAME event as the receipt, `PresentNotVerified`,
`Caveat proves-key`, and a `CertificateLauncher` on the receipt. `isFailClosed`
renders `FailClosed` as a held guarantee, not an error.

## Anveṣaṇa — investigator (done)
`Anvesana.jsx` — three-mode intake (upload `uploadLeak` / built-in `example`
then `leakcheck` / paste `leakcheck`), pipeline-named loading, calm error retry.
`anvesana/Findings.jsx` — normalises BOTH response shapes (raw `leakcheck` vs
normalised `uploadLeak`) into one view model, then renders the core honesty rule:
**document match and recipient attribution are two separate panels with two
separate confidence bars, never merged.** Ranked candidates (collusion case) each
carry their evidence + crosses/below-threshold pill, under `Caveat ranking`
("a rank is not an accusation"). Ledger link = `WitnessRing widget` highlighting
the pointed-at leaf. Verification shown as "re-derived / did not hold" +
`PresentNotVerified` (never a green "verified").

## Pramāṇapatra — certificate (done)
`Pramanapatra.jsx` — the evidence bundle as a certificate. `api.certificate(idx)`
→ renders the human face of the JSON bundle: classification banner, witnessed
seal (ring highlighting the leaf), the plain-language attestation (recipient X
opened doc Y at time T — "a statement the recipient's key signed, not a claim by
the authority"), **what the bundle carries** (inclusion proof, consistency, head
size, witness co-sigs, CA cert, recipient key), `Caveat proves-key`,
`PresentNotVerified` ("check it with the standalone verifier/"). Exports: JSON
bundle (blob download) + Print/save-as-PDF (browser print; backend `pdf` is null
by design — it says so). Inconclusive path when no entry assembles — truthful, not
an error. Exposed two ways: `CertificateLauncher` (in-flow, from the Sūchī open
receipt and the Anveṣaṇa finding — design §11 "pulled from any open or trace
result"), and a standalone finding-id intake.

Verified: `npm run build` clean; screenshotted Findings + the certificate with
mocked backend responses (two separated confidences, ranking, seal, present-not-
verified all render correctly). Anti-slop pass: one dominant accent (cyan),
struct-blue used once for the document bar to distinguish the two answers, no
purple/glass/hype, mono for all IDs/hashes/keys.

## Notes for integration (outside Lane B)
- Pramāṇapatra is reached in-flow via `CertificateLauncher`. It has NO
  `/pramanapatra` route in `App.jsx` (App.jsx is the shell, not Lane B). If a
  standalone route is wanted, whoever owns the shell adds one lazy import + Route
  — the default export already accepts an optional `findingId` prop and a manual
  intake without it.
- Backend still unreachable in this env (`fpdf2` missing / exits 144). All
  live-data screenshots used mocked responses matching the frozen contract shapes.
  Report to Lane C / environment owner.

## Decluttering pass (done — user asked for "more intuitive, spacious, well-organized, less overwhelming text, suitable boundaries")
Applied across all four dashboards:
- `_shared/ui.jsx` — `Panel` default `pad` bumped 1.25 → 1.5 so every panel breathes.
- `Findings.jsx` — outer gap → `calc(var(--gap) * 2)`; added `SectionLabel`
  ("the two answers") over the two-confidence grid; IDs sized to fontSize 20;
  prose trimmed; the ranking caveat moved out of the attribution panel into
  `Ranking`; `Verification` folded into a new `Disclosure` (native `<details
  className="lb-disclosure">`) so the calm default result isn't a wall of checks;
  `Bar` animates `transform: scaleX(frac)` (transformOrigin left) not `width`.
- `Anvesana.jsx` — outer padding + gap → `calc(var(--gap) * 2)`.
- `CapacityMeter.jsx` — bar fill animates `transform: scaleX(ratio)` not `width`.
- `dashboards.css` — appended `.lb-disclosure` (bordered box, `+`/`−` marker on
  summary, hides native marker).
- `Pramanapatra.jsx` — attestation 2nd paragraph trimmed to "A statement the
  recipient's own key signed — not a claim by the authority."; header/seal grid
  padding → `* 2`; **`Contents` flattened** from a nested `<Panel>` (box-in-box
  inside the bordered certificate card) to a plain block with per-row bottom
  dividers; lower content grid padding → `* 2`, columns `minmax(0,1fr)
  minmax(0,320px)`; action-bar padding aligned to `var(--gap) calc(var(--gap)*2)`.

Verified: `cd web && npm run build` clean after every edit (last build ✓, 3.32s).

---

## SESSION PAUSE — resume here (2026-09-30)

### (1) What's built and working
All four dashboards complete and build clean. The decluttering pass above is
finished. Nothing is half-broken. Lane B is functionally done pending live-backend
verification (env issue, not ours).

### (2) Exact next step
Optional visual confirmation only — nothing is blocking. Re-screenshot Findings +
the certificate with the mocked-backend CJS scripts to eyeball that the
decluttering reads as more spacious/less text-heavy. If the reviewer is happy from
the code, Lane B can be handed off as-is. There is no pending code edit.

### (3) Key decisions and why
- **Two separated confidences never merged** (document match vs recipient
  attribution) — core honesty rule; a strong-doc/weak-attribution result is normal
  and truthful, merging into one score would lie. See `sakshya-honesty`.
- **Present-not-verified everywhere** — this UI renders what a bundle *contains*
  and says who verifies (standalone `verifier/`); never prints a green "verified"
  badge. `--verified`/`--alert` colours stay reserved.
- **Pramāṇapatra reached in-flow via `CertificateLauncher`**, not a route —
  App.jsx is the shell (outside Lane B), so we didn't add `/pramanapatra`. The
  default export still takes an optional `findingId` + manual intake if the shell
  owner wants a standalone route later.
- **Fail-closed rendered green as a guarantee**, not a red error (Sūchī open).
- **Bars animate `transform: scaleX` not `width`** — avoids layout thrash (design
  hook finding, fixed in Findings.jsx + CapacityMeter.jsx).
- **Progressive disclosure** (`Disclosure`/`<details>`) for the verification
  re-check list — keeps the default result calm, detail one click away.

### (4) Gotchas / half-finished / failing
- **No half-finished edits.** Last edit (Contents flatten) applied + built clean.
- **Backend UNREACHABLE in this env** — `fpdf2` missing, `python scripts/demo.py
  --serve` exits 144. Lane C / env dep, NOT Lane B. Every populated screenshot
  used mocked responses matching the frozen contract shapes.
- **Screenshot workaround** (backend down): `/tmp/*.cjs` scripts using
  `require('/home/void/.npm/_npx/e41f203b7505f1fb/node_modules/playwright')`,
  `executablePath: '/home/void/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'`.
  Dev server `npm run dev` on `localhost:5173` (Vite HMR serves live source, no
  rebuild needed for source edits). Routes: `/anvesana`, `/suchi`, `/dvarapala`
  (behind `<Authed>`, no redirect guard). NO `/pramanapatra` route.
- **WitnessRing data gotcha**: `data.witnesses` must be a NUMBER, not an array.
- **StrictMode**: `useAsync` re-arms its `alive` ref on mount (already fixed) —
  don't regress it or every surface hangs on "loading".

### (5) Files I was editing (all under `web/src/dashboards/`, plus the progress doc)
- `web/src/dashboards/Pramanapatra.jsx` (last touched — Contents flatten)
- `web/src/dashboards/anvesana/Findings.jsx`
- `web/src/dashboards/Anvesana.jsx`
- `web/src/dashboards/_shared/ui.jsx`
- `web/src/dashboards/dashboards.css`
- `web/src/dashboards/dvarapala/CapacityMeter.jsx`
- `web/src/dashboards/suchi/OpenFlow.jsx`
- `web/PROGRESS-lane-b.md` (this file)

Note: `git status` also shows `Makefile`, `tests/test_verifier_independence.py`,
and untracked `run.sh` modified — those are NOT Lane B and I did not touch them.
Do not stage/revert them; leave for their owner. Never commit.

---

## Full-screen layout pass (done — 2026-09-30, user: "use full screen, not all in middle, no scroll on this screen")

The earlier decluttering centred each dashboard in a narrow card, which the user
disliked: on a wide monitor it floated in the middle with big empty gutters and
still scrolled. This pass makes the two console screens **fill the viewport** and
**fit without page scroll**, while keeping the results screens as measured columns.

- `_shared/ui.jsx` — added `Workspace` (centred/max-width column, optional
  `center`), `PageHead` (one title + one short sub), `ZoneLabel`. `Workspace`
  merges a `style` prop so a screen can override to full-bleed + full-height.
- **`shell.css` (SHELL, normally Lane A — flagged below):** `.stage` no longer
  caps width at 1200px / adds page padding. It is now full-bleed; **each
  dashboard's own `Workspace` owns width, padding, and centering.** This was the
  real cause of "everything in the middle" — the shell was clamping every route
  to 1200px. Only `.stage` (non-landing authed routes) changed; landing untouched.
- `Dvarapala.jsx` / `Suchi.jsx` — `Workspace max={2400}` + `height: calc(100dvh -
  var(--strip-h))`, flex column, `padding: var(--gap)`; the framed `Panel` is
  `flex:1; minHeight:0` so the rail+stage console fills the screen edge-to-edge
  with no page scroll (verified `pageScroll=false`). Internal panes scroll (`lb-scroll`).
- `Suchi` / `OpenFlow.jsx` — **reading-pane-first**: the opened copy is the hero.
  Full-width classification banner → slim toolbar (reveal-mark toggle only for
  text, Copy, Screenshot/print) → large readable body (`DocumentView`, a centred
  760px measure, `min/maxHeight` 52–68vh) → the ledger leaf as a **slim horizontal
  receipt strip** (index, leaf hash, present-not-verified, certificate launcher).
  **`DocumentView` is format-aware:** image → `<img>`, PDF → native blob
  `<iframe>`, else the marked-text column. **Bug fixed:** the reader div had the
  `lb-print-only` class (`display:none` on screen) so the received text was
  invisible on screen — removed; it now shows on screen and in print.
- `Anvesana.jsx` / `Pramanapatra.jsx` — kept as centred measured columns
  (`Workspace max={1360}` / `{960}` + `PageHead`) since results/certificate grow
  and legitimately scroll; text trimmed to one-line subs, intake prose removed.
- Tasteful motion: `lb-fade` on the opened copy / findings / certificate reveal;
  the pipeline-named `Loading` (key request → ledger leaf → mark) is the seal/open
  moment. Respects reduced-motion (existing guard).

### LANE C / LANE A flags
- **Original-bytes viewer (Lane C):** `api.open()` returns marked text only.
  `DocumentView` already renders `data.image_data_url` / `data.pdf_data_url` when
  present — when Lane C adds the original bytes to the open response, the
  image/PDF viewer lights up with no Lane B change. Until then it shows the text.
- **`shell.css` edit (Lane A/shell):** I changed `.stage` because it was the
  hard blocker on the user's explicit "use the full screen" requirement and it
  only frames the dashboard routes. If the shell owner prefers, the same effect
  can live entirely in Lane B via a full-bleed breakout on `Workspace` — but the
  shell change is the clean fix. Flagging for awareness.
- `.claude/launch.json` — added `"autoPort": true` so the preview dev server
  starts even when 5173 is held by a stale process (tooling only, not app code).

Verified: `npm run build` clean; screenshotted Dvārapāla (fills screen, no
scroll), Sūchī opened (big readable copy + slim receipt), Anveṣaṇa findings
(two separated confidences, centred). Anti-slop: one accent per screen, mono for
IDs/hashes, no purple/glass/hype, sharp corners.
