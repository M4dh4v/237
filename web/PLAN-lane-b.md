# PLAN — Lane B (dashboards)

Owns `web/src/dashboards/` only. Consumes `@/components` (frozen stubs), `@/design-system/tokens.css` (CSS vars), `api.*` (real + stubbed methods). Does **not** edit design-system, scenes, components, api.js, or logfirst.

## What already exists (verified)
- Shared stubs importable now: `StatusStrip, PresentNotVerified, FailClosed, Caveat, ClassificationBanner, WitnessRing, SceneFallback` — real props, placeholder visuals. I pass data down; they don't fetch.
- `SealScene` from `@/scenes` — placeholder now, real R3F later. I embed it, never rebuild.
- Shell mounts each dashboard inside `<div className="stage">` with `StatusStrip` above. Dashboards fetch their own data.
- Design-system exposes **only tokens.css** (no `Button/Panel/Chip` primitives — those are Lane A's, not frozen). So Lane B styles with token CSS vars directly; I will not invent a dependency on unfrozen primitives.
- `api.js` real shapes I build against: `documents()->{documents:[{doc_id,words,slots,tardos_positions,tardos_required,guarantee,sealed,recipients,preview}]}`, `adminRecipients()->{recipients:[{recipient_id,role,revoked,serial,kem_alg,sig_alg,ca_signature_ok,device_fp,granted,opened}],note}`, `distribute({doc_id,recipients,classification})`, `open({doc_id,recipient_id,mark,include_pdf})->{receipt,plaintext,marked_text,mark_diff,ledger_entry:{index,leaf,leaf_hash},caveat,payload_manifest}`, `leakcheck({text|image_b64,doc_id?})->{status,document:{doc_id,confidence,ambiguous,candidates},watermark:{recovered,confidence,ledger_index,tardos_positions,tardos_required,tardos_guarantee},candidates,verification,ledger_sessions,notes,caveat}`, `ledgerHead()->{tree_size,...}`, `witnesses()`, `anchors()`.
- New stubbed methods: `uploadSource(file)`, `composeSource({title,body})`, `createRecipient({displayName,role})`, `uploadLeak(file)` (stub returns `{documentMatch,recipientAttribution,pages}` — Lane C will return the leakcheck shape + pages; I normalize both), `sourceCapacity(docId)`, `certificate(findingId)`.

## Local structure (all under dashboards/)
```
dashboards/
  Dvarapala.jsx   Suchi.jsx   Anvesana.jsx   Pramanapatra.jsx   (route entries)
  dvarapala/  SourceStep, RecipientStep, ClassifyStep, SealStep, CapacityMeter, StepRail
  suchi/      IdentityChip, InboxList, ReaderPane, OpenGate
  anvesana/   EvidenceIntake, PipelineTrail, FindingCard, CollusionRanking
  pramanapatra/ Certificate (also the export builders)
  _shared/    useAsync.js (loading/error/empty state machine), Async.jsx (renders
              pipeline-step loading / error+retry / empty — never a bare spinner),
              ui.js (tiny token-styled Button/Panel/Field/Pill/Tabs helpers, LOCAL
              to Lane B so I don't depend on Lane A's unfrozen primitives),
              money-free demo data helpers, mono() hash formatter.
```
`_shared/ui.js` reads only token CSS vars — sharp corners (`--radius`), one accent per screen, no glass, no gradient text. This is Lane-B-local, not a reach into design-system.

## The four builds (commit after each)

### 1. Dvārapāla (sender) — §7
- **StepRail** left: source → recipients → classification → seal, doubles as progress spine (current step gold-rimmed, one accent).
- **SourceStep**: one drop panel, four quiet tabs — Upload (`uploadSource`), Compose (`composeSource`), Corpus (`documents()` picker, first-class/default), Paste (`composeSource` fast path). Preview pane + **CapacityMeter** (`positions` vs `needed`=1201: green ample / amber thin) with `text-domain` Caveat under uploads.
- **RecipientStep**: cards from `adminRecipients()` — name, role, short fingerprint (mono), status; toggle-select (selected lifts + gold rim); running "sealing for N". Inline **+ new recipient** form → `createRecipient()`, new card animates in pre-selected. Revoked cards grey, unselectable. Search + "all active".
- **ClassifyStep**: banded chips `UNCLASSIFIED · RESTRICTED · CONFIDENTIAL · SECRET` (thin top-band, no garish fill) → stamps `ClassificationBanner` top+bottom on preview; optional handling-caveat line.
- **SealStep**: single primary **Seal & Distribute** → embed `SealScene` from `@/scenes`; on success `distribute()`; ends **unopened** with caption "Sealed. Nothing is written to the ledger until a recipient opens it — that is the gate." Then receipt (doc id, recipients, classification, container hash) + Download container + soft "switch to a recipient to open it" deep-link.
- Right **ledger-pulse strip**: `WitnessRing scale="strip"` fed `ledgerHead()`/`ledgerEntries()`, polled; if quorum can't be met, warn before sealing.
- Honesty: seal button disabled + `BACKEND_HINT` when unreachable; never "unbreakable".

### 2. Sūchī (recipient) — §8
- **IdentityChip**: name, role, short fingerprint, active/revoked (from `adminRecipients()` filtered to current role identity).
- **InboxList**: rows from `documents()` (sealed for me) + local opened-state; newest first; polls; new rows slide+pulse once, "N new" badge; state pills sealed/opened/unavailable (revoked reason on hover).
- **Open flow**: sealed row → reader shows sealed state + honest sub-line → **Open** plays compact gate in-pane using `WitnessRing scale="widget"` (glyph → head ticks up → unlock), then `open({mark:true})`. Quorum-fail/revoked → `isFailClosed(err)` → shared **FailClosed** (green guarantee), content never shown.
- **ReaderPane**: `ClassificationBanner` top+bottom, body text, sender + open-time meta. **Copy text** ("your hidden mark travels with the text") + **Screenshot** (canvas → PNG, "even a screenshot carries the mark"). **Marked-copy overlay** toggle (off by default) faintly highlighting `mark_diff` positions.
- Empty ("No documents yet…"), revoked mid-session, offline states.

### 3. Anveṣaṇa (investigator) — §9
- **EvidenceIntake** tabs: Paste (`leakcheck({text})`), Drop image (`leakcheck({image_b64})`, show OCR'd text back), Upload whole doc (`uploadLeak(file)`, per-page extraction status). `text-domain` Caveat.
- **PipelineTrail**: honest step-by-step (read text → identify doc TF-IDF → align LCS → extract soft-bits → seed search → match ledger → assemble), each ticks green or stops honestly with reason + suggestion. This IS the loading state.
- **FindingCard**: **two separated confidences**, never merged — Document match (`document.confidence`) and Recipient attribution (`watermark.confidence` / candidate) with fixed `proves-key` Caveat beneath. Full recovery → gold name card + four **present** checks (via `PresentNotVerified`, never "verified"). Partial → rank candidates, don't name one.
- **CollusionRanking**: when evidence is a mix → ranked list w/ scores + prominent `ranking` Caveat showing real numbers (`tardos_positions` vs `tardos_required`).
- Link into full ring: `WitnessRing scale="full" highlightLeaf={ledger_index} interactive onInspect` → route `/ledger`; **Export evidence** → Pramāṇapatra.
- No-match honest dead-ends; `PresentNotVerified` persistent; offline.

### 4. Pramāṇapatra — §11
- Wax-sealed certificate view: header (SĀKṢYA seal, cert id, gen time, source classification, `PresentNotVerified` stamp), the finding (two separated confidences as clear numbers), fixed non-removable `proves-key` caveat line, proof chain (leaf, inclusion proof, witness co-sigs w/ fingerprints, anchor), "how to verify" → standalone `verifier/`, collusion honesty if ranking.
- Green **present** checks (never verified). Export **PDF** (print-to-PDF of the styled cert via `window.print()` + print CSS scoped to the cert — no new dep) + **JSON** (`certificate()` json, downloaded as blob). Inconclusive findings export an honest **"inconclusive finding"** report, never a firm certificate.

## Cross-cutting rules I enforce (§12 + honesty skill)
- Every async surface: loading = named pipeline/step text (never bare spinner), error = message + **retry**, meaningful empty state. Centralized in `_shared/Async.jsx` + `useAsync`.
- Honesty rails sacred: present-not-verified (never "verified"), fail-closed = green guarantee, two confidences never merged, all four caveat kinds where material, truthful ledger/copy framing.
- Anti-slop self-check per screen: count tells (purple wash, glass-default, 3-card grid, rounded-everything, gradient text, hype copy, uniform fade-up, pure-white-on-black). 2+ ⇒ revise. Screenshot via Playwright, iterate twice.
- Air-gap: no external fetch; only tokens + local assets.

## Verify before done
`cd web && npm run build` passes; Playwright screenshot each dashboard, count tells, iterate ×2; update `web/PROGRESS-lane-b.md` after each.

## Open calls (proceeding with defaults unless you object)
- Classification labels: design-plan defaults `UNCLASSIFIED · RESTRICTED · CONFIDENTIAL · SECRET`.
- PDF export via browser print (no new dep) rather than a PDF lib — air-gap friendly, zero deps.
- "Current recipient identity" for Sūchī: first active recipient from `adminRecipients()` (god-mode picks). No login (per contract §4).
