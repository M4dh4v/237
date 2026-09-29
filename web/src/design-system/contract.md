# FROZEN CONTRACT — SĀKṢYA frontend

This file is the treaty between the three parallel lanes. **Freeze it on `main` before branching worktrees.** If a lane needs to change anything here, it stops, the change is made on `main`, and all worktrees rebase. Nothing in here is edited inside a lane branch.

Contents: (1) design tokens, (2) the `api.js` surface, (3) shared component prop interfaces, (4) routing + role model.

---

## 1. Design tokens — `web/src/design-system/tokens.css`

CSS custom properties on `:root`. **Every lane reads these; no lane hardcodes hex.** Names are frozen; the *values* are set once by the chosen theme (see the playbook). Required variable names:

```
/* surfaces */        --bg  --bg-panel  --bg-elevated  --hairline
/* text */            --ink  --ink-muted  --ink-faint
/* structure */       --struct-1  --struct-2   (the cool gradient stops)
/* the one accent */  --accent  --accent-soft
/* reserved status */ --verified  --alert
/* type */            --font-display  --font-body  --font-mono
/* motion */          --ease-out  --dur-fast  --dur-slow
/* geometry */        --radius (2–6px)  --gap  --rail-w  --strip-h
```

Reserved-color rule is enforced in code review: `--verified` only where something was checked, `--alert` only at real failure/unknown.

---

## 2. `web/src/api.js` — Lane C owns; A & B consume only

**Existing (unchanged):** `demoState, documents, distribute, open, leak, downloadContainer, containerBytes, adminRecipients, revokeRecipient, reinstateRecipient, leakcheck, example, ledgerHead, ledgerEntry, ledgerEntries, witnesses, health, anchors`. All throw `ApiError`; keep `isUnreachable`, `isFailClosed`, `toImageDataUrl`, `BACKEND_HINT`.

**New glue methods (Lane C adds; signatures frozen so A & B can call against stubs immediately):**

```js
// 1. seal an arbitrary uploaded file (PDF/image/text) -> sealable document body
api.uploadSource(file /* File */, opts) 
  // -> { docId, preview, capacity: { positions, needed, strength } }

// 2. compose a document in-app
api.composeSource({ title, body }) 
  // -> { docId, preview, capacity }

// 3. enroll a new recipient from the UI (generates PQC keypair server-side)
api.createRecipient({ displayName, role }) 
  // -> { recipientId, displayName, role, fingerprint, status }

// 4. trace tool: submit a whole uploaded document (PDF/doc), multi-page
api.uploadLeak(file /* File */, opts) 
  // -> same shape as api.leakcheck(...) result, with per-page extraction status

// 5. (optional) watermark capacity for a chosen doc
api.sourceCapacity(docId) // -> { positions, needed, strength }

// 6. (optional) render the Pramāṇapatra from an existing evidence bundle
api.certificate(findingId) // -> { pdf: blob-ref, json }
```

Until Lane C lands these, they exist as **stubs** returning realistic mock data (added in the P0 bootstrap) so Lanes A/B are never blocked. Backend maps them to design-plan §13.2 endpoints; **no new crypto, glue only.**

---

## 3. Shared components — Lane A owns; Lane B imports, never edits

Import path: `@/components/…` and `@/design-system/…` (Vite alias `@` → `web/src`). Frozen props:

```jsx
<StatusStrip offline ledgerLeaves quorum={{have,need}} witnessesUp liteMode onToggleLite onRoleSwitch />
<PresentNotVerified inline?  />                    // the calm chip + verifier pointer
<FailClosed reason />                              // green guarantee panel (feed it the ApiError)
<Caveat kind={'proves-key'|'ranking'|'text-domain'|'simulated'} />
<ClassificationBanner level position={'top'|'bottom'} caveat? />
<WitnessRing scale={'strip'|'widget'|'full'} data={ledgerData} highlightLeaf? onInspect? interactive? />
<SceneFallback name />                             // static poster used by lite/reduced-motion
```

`WitnessRing` is ONE component at three scales (strip in the sender pulse, widget in the recipient open, full in the shared ledger/investigator). Same data, same object — this is a truth claim, so it must literally be the same component.

Shared honesty components are dumb/presentational: they take data via props, do no fetching. Dashboards (Lane B) fetch via `api.*` and pass down.

---

## 4. Routing + roles — Lane A defines the shell, Lane B fills dashboards

```
/                     Landing (Pravāha) — scroll journey, one-time, "skip to app" always present
/darsana              Role threshold — three doors: sender · recipient · investigator (+ labelled demo god-mode)
/dvarapala            Sender dashboard        (Lane B)
/suchi                Recipient inbox         (Lane B)
/anvesana             Investigator trace      (Lane B)
/ledger               Shared Akṣaya Śṛṅkhala full view (Lane A component, routed here)
```

Role state is a simple UI role-select (frictionless, for the demo) held in a small context provider Lane A ships in the app shell; god-mode toggle lets one screen drive all three, clearly labelled "demo convenience — a real deployment separates these by credential." No login. `StatusStrip.onRoleSwitch` returns to `/darsana`.

The app shell (`App.jsx`, router, role context, `StatusStrip` mount, lite-mode state, `<Suspense>` boundaries for lazy scenes) is **Lane A**. Lane B mounts *inside* the shell's dashboard routes and never edits the shell.
