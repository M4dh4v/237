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

## Pending
- Sūchī (recipient), Anveṣaṇa (investigator), Pramāṇapatra (certificate).
