# SĀKṢYA — Project Overview

> **One line:** give the same secret file to many officers; every copy reads like
> an ordinary copy but quietly knows who opened it, and the record of who-opened-what
> is held by many witnesses so no single admin can rewrite it.

**SIH problem SIH26237 — WESEE / Indian Navy.** An offline, air-gapped,
post-quantum forensic-attribution instrument for classified document distribution.

This document is the single-file map of the whole project: what it is, how it is
built, what each directory does, and what tooling it stands on. The authoritative
*design* documents remain `SAKSHYA-MASTER-DESIGN-PLAN.md` (the design bible) and
`SAKSHYA-FRONTEND-PLAYBOOK.md` (how to build it).

---

## 1. What the system does

A sender **seals** one document. It goes out to many authorised recipients, each
holding their own copy. When a recipient **opens** it, three things happen as one
atomic event:

1. The recipient's own **ML-DSA-65** signature over "I am opening document X now"
   is written to a shared, tamper-evident Merkle ledger, co-signed by independent
   **Sākṣī witness** nodes.
2. **Only after that record is committed** (quorum met) is the content key released.
   This is the *log-before-open* invariant, enforced in code.
3. The copy handed back is quietly fingerprinted with a linguistic watermark whose
   seed is `HKDF(committed leaf hash)` — so the mark and the ledger entry are
   derived from the *same* event.

If the document leaks, the investigator drops the leaked text / screenshot / whole
document into the trace tool. It identifies the source document, aligns the leak to
the canonical text, recovers the hidden soft-bits, self-validates the ledger pointer,
and returns the recipient — with an independently verifiable evidence bundle.

Everything runs **offline**: no cloud, no public chain, one local origin
(`127.0.0.1`). That is a requirement, not a limitation.

### The naming (each name is its function)

| Name | Meaning | In the product |
|---|---|---|
| **SĀKṢYA** | Evidence, testimony | The whole platform |
| **Sākṣī** | Witness | Each independent ledger node |
| **Dvārapāla** | Gatekeeper | Sender / sealing + gated-open surface |
| **Guptamudrā** | Hidden seal | The invisible mark placed at open |
| **Abhijñāna** | Token of recognition | The identity pointer inside the mark |
| **Akṣaya Śṛṅkhala** | Imperishable chain | The tamper-evident PQC ledger |
| **Anveṣaṇa** | The investigation | The forensic trace tool |
| **Yantrachihna** | Device mark | Device + session fingerprint in each open |
| **Pramāṇapatra** | Certificate of proof | The exportable, verifiable evidence file |
| **Sūchī** | The register / index | The recipient inbox |
| **Darśana** | Viewing / audience | The role-select threshold |
| **Pravāha** | The flow | The scroll-driven landing |

---

## 2. Repository layout

```
237/
├── logfirst/                  # Python backend package (v0.1.0)
│   ├── models.py              # byte-exact canonical wire contract (dataclasses)
│   ├── sealed.py              # .lfdoc / LFPAY container framing
│   ├── pdfdoc.py              # fpdf2 document rendering
│   ├── proc.py                # child-process orphaning guard (PR_SET_PDEATHSIG)
│   ├── crypto/                # PQ primitives: ML-KEM, ML-DSA, SLH-DSA, AEAD, KDF, CA, mTLS
│   ├── ledger/                # RFC 6962 Merkle log, STH, anchors, witness quorum client
│   ├── witness/               # standalone co-signing witness node (process + HTTP)
│   ├── watermark/             # linguistic synonym mark + Tardos collusion codes
│   ├── forensics/             # identify → align → extract → verify → investigate → bundle
│   ├── authority/             # FastAPI authority: server.py, store.py, demo_api.py (glue)
│   ├── data/                  # corpus, deployment, scenario wiring, OCR harness, generator
│   └── client/                # recipient ClientNode (open path)
├── verifier/                  # STANDALONE verifier — imports nothing from logfirst
│   ├── core.py                # re-implemented canon + Merkle (stdlib only)
│   └── verify.py              # full bundle verification (+ liboqs for signatures)
├── web/                       # React 18 + Vite console
│   ├── src/
│   │   ├── design-system/     # tokens, primitives, fonts, FROZEN contract.md
│   │   ├── components/        # shared honesty layer + WitnessRing (3 scales)
│   │   ├── scenes/            # R3F scenes + *.static.jsx fallbacks
│   │   ├── dashboards/        # Dvārapāla, Sūchī, Anveṣaṇa, Pramāṇapatra
│   │   ├── shell/             # role + lite-mode context providers
│   │   ├── api.js             # the single backend surface (ApiError contract)
│   │   ├── container.js       # browser-side .lfdoc parser (mirrors sealed.py)
│   │   └── App.jsx            # router, lazy routes, Authed shell
│   ├── public/fonts/          # 7 vendored woff2 (no CDN)
│   └── vite.config.js         # @ alias + API proxy → 127.0.0.1:8443
├── scripts/
│   ├── demo.py                # the server (--serve) and a scripted 8-step story (--scripted)
│   ├── check_env.py           # preflight: python, liboqs algorithms, tesseract, optional deps
│   └── tamper_demo.py         # six real attacks against the ledger
├── tests/                     # pytest suite (crypto KATs, ledger fail-closed, verifier independence…)
├── demo-data/                 # git-tracked sample deployment (keys, anchors, artifacts, mTLS)
├── run.sh                     # one-command dev run (backend + console)
├── ecosystem.config.js        # pm2 deployment (sakshya-api + sakshya-ui)
├── Makefile                   # bootstrap / demo / tamper / generate / verify / test targets
├── pyproject.toml             # deps split into core + extras (service/forensics/ocr/qr/dev)
└── requirements.txt           # flat list for `pip install -r`
```

---

## 3. The system flow (one document, end to end)

```
  SENDER (Dvārapāla)
    upload / compose / corpus  →  seal (render PDF, AES-256-GCM, ML-KEM-768 per recipient)
                               →  .lfdoc container

  RECIPIENT (Sūchī)  ── POST /open ──▶  AUTHORITY (Dvārapāla gate)
       ▲                                  1. recipient known + not revoked
       │                                  2. CA-signed certificate valid
       │                                  3. authorised for this document (default-deny)
       │                                  4. ML-DSA request signature verifies
       │                                  5. COMMIT: Merkle append + witness quorum   ◀── the gate
       │                                  6. only now: unwrap content key for this session
       │
       └── plaintext + marked copy (seed = HKDF(committed leaf hash))

  LEDGER (Akṣaya Śṛṅkhala)
    RFC 6962 Merkle tree → STH signed by log key → co-signed by Sākṣī witnesses
    (refuse equivocation / rollback / unproven extension) → periodic SLH-DSA anchor

  INVESTIGATOR (Anveṣaṇa)  ── leaked text / image / PDF ──▶
    OCR → TF-IDF identify → LCS align → soft-bit recover → RS-decode pointer
    → self-validating seed search → verify entry independently → rank / attribute
    → PRAMĀṆAPATRA certificate (PDF + JSON) → standalone verifier/
```

**The invariant that holds it together:** *commit-to-ledger-with-witness-quorum
precedes any key release*, and the watermark seed is `HKDF` of the committed leaf
hash — so the mark on a leaker's disk and the ledger record naming them are the
same object.

---

## 4. Backend architecture (`logfirst/`)

### 4.1 Cross-cutting foundation

| Module | Role |
|---|---|
| `models.py` | Byte-exact wire contract. `canon()` = canonical JSON (sorted keys, compact, UTF-8). Dataclasses `Certificate`, `DeviceRecord`, `DecryptionRequest`, `STH` each carry `tbs()` (strips own signature). Field order is load-bearing — changing it silently invalidates signatures. |
| `sealed.py` | Container formats, no keys/crypto. `LFPAY\0\1` framed payload (manifest/text/pdf), `LFDOC\0\1` sealed container. `compare()` reports header↔manifest disagreement (the header is an unauthenticated label; the AEAD-protected manifest is truth). CLI-able. |
| `pdfdoc.py` | fpdf2 rendering of canonical and marked PDFs. Fails loudly if a glyph can't be drawn (fontTools cmap check). Vendored fonts; deterministic `created` timestamp. |
| `proc.py` | `PR_SET_PDEATHSIG` preexec guard so witness subprocesses die with their parent (closes the fork/exec race). |
| `client/node.py` | Recipient `ClientNode`: signs `DecryptionRequest`, generates a fresh ML-KEM ephemeral per open, unwraps the session key, discards it, and can embed the Tardos codeword + pointer into a marked copy. Holds no key, no share, no cached plaintext. |

### 4.2 `crypto/` — post-quantum primitives

| Module | Contents |
|---|---|
| `pqc.py` | liboqs. `ML-KEM-768` (FIPS 203), `ML-DSA-65` (FIPS 204), `SLH_DSA_PURE_SHA2_128S` (FIPS 205). `verify()` returns `False` on malformed input, never raises (fail-closed). |
| `aead.py` | AES-256-GCM (`cryptography`), 12-byte nonce, `doc_id` as AAD. |
| `kdf.py` | HKDF-SHA256 with domain-separated `info` constants: `wrap`, `wm-seed`, `wm-keystream`. |
| `onetime.py` | One-time key lifecycle: authority holds the only copy of `K`; every response is inert outside its session (KEM-encap → HKDF-wrap → AES-GCM). |
| `ca.py` | Offline root CA (ML-DSA). Issues certificates binding an ML-KEM + ML-DSA pubkey to an identity. `encrypt_framed_payload` / `open_payload` (verifies text + PDF hashes). |
| `mtls.py` | Transport X.509 with **classical ECDSA P-256** — a knowing trade. The ML-DSA body signature is the load-bearing check; TLS is defence in depth. |

### 4.3 `ledger/` — transparency log

| Module | Contents |
|---|---|
| `merkle.py` | RFC 6962 pure functions: `leaf_hash = SHA256(0x00‖data)`, `node_hash = SHA256(0x01‖L‖R)`, root, inclusion proof, consistency proof, verifiers. |
| `log.py` | SQLite-WAL append-only log. `append()` signs the STH, gathers quorum **inside** the transaction, rolls back on `QuorumNotMet`. `gated_append_for_decryption()` is **the only path to a content key** and returns the watermark seed bound to the leaf hash. |
| `anchor.py` | SLH-DSA-signed JSONL anchors over `(tree_size, root)`, plus a 20-hex-char transcribable `short_code` and optional QR. |
| `witnesses.py` | `WitnessClient` (HTTP), `WitnessQuorum.collect()` — computes a **per-witness** consistency proof from each witness's own last signed size. `QuorumNotMet`, `WitnessUnavailable`. |

### 4.4 `witness/` — independent witness nodes

| Module | Contents |
|---|---|
| `signer.py` | `WitnessSigner` persists its key + `signed` map (0600, atomic replace). Three refusal rules before co-signing the same `STH.tbs()`: **R1** no equivocation (same size, different root), **R2** no shrinking below high-water mark, **R3** must supply a valid consistency proof from its own last root. Idempotent. |
| `node.py` | Standalone FastAPI process per witness (`python -m logfirst.witness.node --id w1 --port 9101`). Routes: `GET /health`, `GET /pubkey`, `POST /cosign` (409 on refusal), `GET /history`. |

### 4.5 `watermark/` — attribution channel

| Module | Contents |
|---|---|
| `linguistic.py` | The primary channel: synonym substitution over a 256-pair lexicon. A *slot* is an occurrence of either synonym; one bit per slot via payload XOR keystream. `embed()` / `extract()` (soft bits). Refuses rather than weakly marking below the minimum slot count. |
| `tardos.py` | Symmetric Tardos collusion-resistant fingerprint codes (Škorić et al. 2008). `code_length`, `generate` (position-major, prefix-stable), `scores`, `threshold`, `classify_scores` → `NO_MARK` / `SINGLE_USER` / `COLLUSION`. |
| `payload.py` | Ledger pointer = 2 bytes + 3 Reed-Solomon parity symbols (40 bits) via `reedsolo`; unread slots become cheap RS *erasures*. `plan_for_document()` is the single entry point for both marker and investigator and returns a `guarantee` of `formal` / `ranking-only` / `none`. |
| `ocr.py` | Shells out to system `tesseract` (`--psm 6`). Word merge/split is the main error source. |

### 4.6 `forensics/` — the leak-check pipeline

| Module | Contents |
|---|---|
| `identify.py` | Which document? TF-IDF word n-grams (scikit-learn) — deliberately not a transformer; auditable at corpus scale. `MIN_IDENTIFY_SCORE = 0.25`. |
| `align.py` | Maps leak → canonical via `difflib.SequenceMatcher` LCS; ragged regions become unmapped (erasures). |
| `evidence.py` | Independent per-entry verification from public outputs only: recipient ML-DSA signature, Merkle inclusion, STH signature, each witness signature. `verified` is true **only if every check passes**. |
| `bundle.py` | Evidence bundle export: inclusion proof + STH *at the entry's commit size*, consistency-to-head, anchors, recipient certificate, algorithm block. `from_deployment()` reads witness keys from their own state files. |
| `investigate.py` | The `Investigator`: OCR → identify → align → soft bits → RS pointer + Tardos trace → independent verification → rank. Breaks seed circularity by requiring the seed from entry *N* to decode a pointer to *N* (self-validating). Keeps **two separate confidences** (`doc_confidence`, `watermark_confidence`) and carries the fixed `ATTRIBUTION_CAVEAT` (proves key/device/session, not the human). |
| `export.py` | CLI: `python -m logfirst.forensics.export --data DIR --indexes … --out bundle.json`. |

### 4.7 `authority/` — key authority + HTTP surface

| Module | Contents |
|---|---|
| `server.py` | `Authority.seal()` and `Authority.open_document()` — the 6-step gate (known+not-revoked → valid cert → default-deny authorisation → valid request signature → **commit** → only then release). `build_app()` with `scenario=None` gives the production shape with no demo routes. |
| `store.py` | Mutable operational state (recipients / documents / grants / sessions), a **separate database from the evidence ledger**. Nothing in attribution trusts it; a compromised store cannot rewrite history. |
| `demo_api.py` | **Thin glue only.** Upload/compose/certificate adapters that feed existing pipeline functions. No cryptography of its own; removing it leaves every guarantee intact. |

### 4.8 `data/` — corpus, deployment, demo wiring

| Module | Contents |
|---|---|
| `corpus.py` | Synthetic template prose generated **to a carrier-density target** (feedback loop). Honest note: template prose, so measured densities are achievable, not typical. |
| `deploy.py` | `Deployment` (CA/server keys, witness ports, quorum, Tardos config) + `WitnessFleet` — starts witnesses as separate OS processes on ports 9101–9103, refusing a dirty port. |
| `scenario.py` | Wires Deployment + WitnessFleet + corpus + Store + LedgerLog + Authority into a runnable demo; builds `ClientNode`s, leak generators (text / screenshot / collusion), and the `SIMULATED` disclosure tuple. |
| `harness.py` | OCR degradation harness (jpeg / resize / blur / contrast / rotation / combo) reporting channel BER and post-vote BER. Models a screenshot, not a real photo — a lower bound. |
| `generate.py` | Full synthetic dataset generator/CLI + `verify()` that re-runs leak-check over every generated leak. |

---

## 5. HTTP API surface

### Core authority routes (`logfirst/authority/server.py`) — always present

```
GET  /health
GET  /ledger/head
GET  /ledger/entry/{index}
GET  /ledger/entries?limit=&order=
GET  /ledger/proof/{index}?tree_size=
GET  /witnesses
POST /documents
GET  /documents
POST /open              # 503 fail-closed | 403 denied
POST /anchor
GET  /anchors
```

### Demo / glue routes (`logfirst/authority/demo_api.py`) — only when a scenario is attached

```
GET  /demo/state
GET  /demo/documents
GET  /demo/documents/{doc_id}.lfdoc
POST /demo/distribute
POST /demo/open                        # 503 fail-closed | 403
POST /demo/leak                        # kinds: text | screenshot | collusion
POST /leakcheck
GET  /leakcheck/example/{kind}
GET  /demo/admin/recipients
POST /demo/admin/revoke
POST /demo/admin/reinstate
POST /demo/source/upload               # NEW glue (multipart)
POST /demo/source/compose              # NEW glue
GET  /demo/source/{doc_id}/capacity    # NEW glue
POST /demo/admin/recipients/create     # NEW glue
POST /leakcheck/upload                 # NEW glue (multipart)
POST /evidence/certificate             # NEW glue
```

Every endpoint fails closed and returns the same error shape the frontend already
understands (`ApiError` with `isFailClosed` / `isUnreachable`).

---

## 6. Frontend architecture (`web/`)

**React 18 + Vite 5. No TypeScript, no state library, no UI kit dependency.**
Styling is inline style objects + plain CSS driven entirely by design tokens.

### 6.1 Entry, routing, shell

- `main.jsx` mounts `<App/>` and imports the only global CSS: `tokens.css` and `shell.css`.
- `App.jsx` → `<ShellProvider><BrowserRouter><Routes>`; scenes **and** dashboards are route-level `lazy()` + `<Suspense>`.

| Route | Screen | Owner |
|---|---|---|
| `/` | Landing (Pravāha) — scroll journey | Lane A |
| `/darsana` | Role threshold — three doors + labelled demo god-mode | Lane A |
| `/dvarapala` | Sender dashboard | Lane B |
| `/suchi` | Recipient inbox + open | Lane B |
| `/anvesana` | Investigator trace | Lane B |
| `/ledger` | Full Akṣaya Śṛṅkhala witness ring | Lane A |
| `/_ds` | Dev-only design gallery | Lane A |

`shell/context.jsx` holds two contexts: `RoleContext` (`role`, `godMode`) and
`LiteContext` (`lite`, seeded from `prefers-reduced-motion`). Lite mode is the
manual escape hatch that gates every 3D scene's static poster. **Role is a
frictionless UI select, explicitly not the security model.**

### 6.2 Transport — `api.js`

The single backend surface. Every call throws `ApiError` (never returns null on
failure). Three transports: JSON `request()`, multipart `postForm()`, and
`requestBlob()`. Exports `ApiError`, `isUnreachable()`, `isFailClosed()`
(status 503 **and** `detail` contains `fail-closed`), `BACKEND_HINT`,
`toImageDataUrl()`.

- **Existing methods:** `demoState, documents, distribute, open, leak,
  downloadContainer, containerBytes, adminRecipients, revokeRecipient,
  reinstateRecipient, leakcheck, example, ledgerHead, ledgerEntry, ledgerEntries,
  witnesses, health, anchors`.
- **New glue methods:** `uploadSource`, `composeSource`, `createRecipient`,
  `uploadLeak`, `sourceCapacity`, `certificate`.

`vite.config.js` proxies the API prefixes (`/demo /leakcheck /ledger /witnesses
/health /documents /open /anchors`) to `http://127.0.0.1:8443`, so the bundle uses
same-origin **relative** URLs. `vite preview` reuses the same proxy — which is why
the production deployment must run through `vite preview`, not a static server.

### 6.3 Design system (`src/design-system/`) — Lane A owns

Theme **"Abyssal Sonar"** (coldest, most instrument-like of the three playbook themes).

- `tokens.css` — surfaces, ink, structure gradient, one accent, reserved status
  colors (`--verified` green only where something was actually checked,
  `--alert` red only at real failure/unknown), fonts, motion, geometry.
- `scale.css` — spacing / type / shadow scale derived from tokens.
- `fonts.css` — 7 local `@font-face` (Space Grotesk display, Inter body,
  JetBrains Mono for hashes/keys/ids). No CDN.
- `primitives.jsx` — `Button`, `Panel`, `Chip`, `Banner`, `Hash`.
- `contract.md` — **the FROZEN lane treaty**: required token names, the `api.js`
  surface, shared component prop interfaces, routing + role model.

### 6.4 Shared honesty layer (`src/components/`) — Lane A owns

Dumb, presentational, props-only components that carry the project's credibility:

| Component | Purpose |
|---|---|
| `StatusStrip` | Always-visible truth strip: `OFFLINE · 127.0.0.1:8443 · ledger N leaves · quorum m/n`. Dot is green when reachable, red when not — never decorative. |
| `PresentNotVerified` | The #1 honesty rule: the browser cannot verify PQC signatures, so it prints "present, as received" and points at the standalone verifier. Never green. |
| `FailClosed` | Green-framed **guarantee** panel (not a red error): "the system refused to release the key because it could not commit the record." |
| `Caveat` | Four fixed kinds with frozen copy: `proves-key`, `ranking`, `text-domain`, `simulated`. |
| `ClassificationBanner` | Sticky top/bottom handling label — a label, not an alert; spends no reserved colors. |
| `SceneFallback` | Shared static-poster frame for lite / reduced-motion. |
| `WitnessRing` | **One** R3F component at three scales (`strip` 48 / `widget` 220 / `full` 480), same data object — a truth claim, so it must literally be the same component. Falls back to `WitnessRing.static.jsx` (pure SVG) when lite / reduced-motion / no WebGL. Uses `frameloop="demand"`, dpr ≤ 1.5, instanced blocks, unlit materials. |

### 6.5 3D scenes (`src/scenes/`)

Stack: `@react-three/fiber` + `@react-three/drei` + `three`, scroll bound with
**Lenis**, reveals with **Framer Motion**. Token colors are read from CSS custom
properties at runtime — no hardcoded hex in meshes.

| Scene | Role |
|---|---|
| `Pravaha.jsx` | The scroll-driven landing (six stations, one persistent canvas). |
| `PravahaScene.jsx` | The landing's fixed R3F canvas: paper through-line, 50 instanced crowd copies, gate that opens *after* the seal block turns gold, witness ring with a quarantined tampered node, 6 instanced ledger blocks. |
| `PravahaMotif.jsx` | Token-only static SVG posters per station — the landing's fallback path. |
| `useLenisProgress.js` | One Lenis instance; writes scroll progress into a **ref** (no per-frame React re-render). Landing-only. |
| `WitnessRingScene.jsx` | The `/ledger` full view — mounts the real `WitnessRing scale="full"`. |
| `GateScene` / `SealScene` / `TraceScene` (+ `.static.jsx`) | Currently stubs / placeholders; `SealScene` is used by the sender's seal step. |

**Every scene ships a static fallback**, selected by lite mode, reduced-motion, or
no-WebGL. The rule: 3D only where it explains something.

### 6.6 Dashboards (`src/dashboards/`) — Lane B owns

| Dashboard | What it does |
|---|---|
| `Dvarapala.jsx` (sender) | 4-step wizard (source → recipients → classification → seal). Source has 4 tabs (corpus / upload / compose / paste) with an honest Tardos **capacity meter**; recipient step enrolls inline; seal shows the receipt and mounts the *unopened* container with the caption "Nothing is written to the ledger until a recipient opens it." Left rail carries a live `LedgerPulse` (witness ring at strip scale). |
| `Suchi.jsx` (recipient) | Identity chip + polling inbox + `OpenFlow`. Opening calls `api.open`; fail-closed is rendered as a green **guarantee**, not an error. The opened reader exposes copy-text / screenshot (both of which still carry the mark), a `mark_diff` reveal, the ledger-leaf receipt, `PresentNotVerified`, and the certificate launcher. |
| `Anvesana.jsx` (investigator) | Three intake modes (upload / example / paste) with a narrated pipeline trail. `Findings.jsx` folds both response shapes into one view model and shows **two separate confidences, never averaged**, plus collusion ranking, the ledger link, and a verification disclosure that says "re-derived / did not hold" — never a fake green badge. |
| `Pramanapatra.jsx` (certificate) | Renders the evidence bundle as a certificate: classification banner, seal, plain-language attestation, the fixed proves-key caveat, JSON download, print, and an explicitly truthful `Inconclusive` state. **Has no route** — launched inline from `OpenFlow` and `Findings`. |

Internal kit (`_shared/`): `useAsync` (an async state machine that supersedes
in-flight calls and survives StrictMode), `Async`/`Loading`/`ErrorState`/`Empty`
(loading is always a narrated step list, never a bare spinner), and `ui.jsx`
(`Panel`, `Button`, `Pill`, `Tabs`, `Metric`, …). Lane B's `ui.jsx` kit is
intentionally separate from Lane A's `design-system/primitives.jsx`.

---

## 7. Verification & independence

`verifier/` is deliberately standalone: `verifier/core.py` imports **only
`hashlib` and `json`** and re-implements `canon` and the RFC 6962 Merkle math from
scratch — a second, independent implementation. `verify.py` adds signature checks
via `oqs`. `tests/test_verifier_independence.py` enforces this both by scanning
imports statically and by verifying a real bundle in a subprocess where importing
`logfirst` raises.

Exit codes: `0` verified · `1` failed (or anchor contradiction) · `2` malformed ·
`3` entries OK but no anchor offered.

`scripts/tamper_demo.py` stages six real attacks (rewrite a committed entry,
re-sign a rebuilt head, witness equivocation, witness rollback, unproven
extension, standalone verifier catch) and shows each one being refused or caught.

---

## 8. Tech stack and dependencies

### Backend (Python ≥ 3.11)

| Dependency | Why |
|---|---|
| `liboqs-python` | ML-KEM-768, ML-DSA-65, SLH-DSA — the **only** non-pure-Python core dep. The native `liboqs.so` must be present at runtime; `scripts/check_env.py` proves it by instantiating each algorithm. |
| `cryptography` | AES-256-GCM, HKDF, X.509/mTLS. |
| `numpy` | Tardos code math. |
| `reedsolo` | Reed-Solomon error correction on the ledger pointer. |
| `fpdf2` | Core: the seal path renders every document to PDF. |
| `pillow`, `pypdf` | Image handling; PDF text-layer extraction for upload adapters. |
| `scikit-learn` | TF-IDF document identification (forensics extra). |
| `pytesseract` | OCR via the system `tesseract` binary (ocr extra). |
| `qrcode` | Optional QR rendering of a ledger anchor (qr extra). |
| `fastapi`, `uvicorn`, `httpx`, `python-multipart` | The authority/witness HTTP services and upload adapters. |
| `pytest`, `pytest-timeout` | Tests (300 s timeout; some stand up real witnesses and sockets). |

Dependencies are split in `pyproject.toml` into core + extras (`service`,
`forensics`, `ocr`, `qr`, `dev`) so a deployment installs only what it runs.

### Frontend

`react` 18.3 · `react-dom` · `react-router-dom` 6 · `@react-three/fiber` 8 ·
`@react-three/drei` 9 · `three` 0.169 · `framer-motion` 11 · `lenis` 1.3 ·
`@fontsource/{inter,jetbrains-mono,space-grotesk}` (vendored locally). Dev:
`vite` 5, `@vitejs/plugin-react`.

### Tooling & deployment

- `run.sh` — one command: installs nothing, reaps stale processes, starts the
  backend + witnesses, waits for `/health`, then starts Vite.
- `Makefile` — `bootstrap`, `check-liboqs`, `check-tesseract`, `demo`,
  `demo-serve`, `tamper`, `generate`, `verify`, `test`, `test-fast`,
  `test-crypto`, `test-ledger`, `clean`.
- `ecosystem.config.js` — pm2 with two apps: `sakshya-api` (uvicorn/FastAPI on
  8443, via the venv python) and `sakshya-ui` (`vite preview` on 7891). The UI
  must run through `vite preview` because it carries the API proxy.

---

## 9. How to run

```bash
# First time only
./run.sh setup          # installs python deps (no venv) + checks the environment

# Every time
./run.sh                # backend → 127.0.0.1:8443, console → 127.0.0.1:5173
```

```bash
python scripts/demo.py --serve --data /tmp/logfirst-demo --words 1800   # backend only
python scripts/demo.py --scripted                                       # 8-step story, no UI
python -m pytest                                                        # full test suite
python -m verifier.verify bundle.json                                   # independent check
make tamper                                                             # six real attacks
```

**The model's working is a hard boundary.** `logfirst/crypto/`, `logfirst/ledger/`,
`logfirst/witness/`, `logfirst/watermark/`, `logfirst/forensics/`, and `verifier/`
are do-not-touch. All new backend work is **thin glue** in
`logfirst/authority/demo_api.py`: adapters that feed existing pipeline functions.
No new crypto, no new watermark channel, no change to what or when gets committed.

---

## 10. Honesty rails (sacred, by design)

1. **Present-not-verified** — the browser presents PQC signatures and proofs but
   never claims to have *verified* them; that is the standalone verifier's job.
2. **Fail-closed shown as a guarantee** — a refused key release renders as a
   green-framed guarantee, not a red error.
3. **Two separated confidences** — "which document" and "which recipient" are
   never averaged into one number.
4. **Caveat system** — proves-key-not-human, ranking-only-collusion,
   text-domain-mark, and simulated-and-disclosed are stated, not buried.
5. **Truthful framing of the ledger** — "many witnesses co-sign a shared,
   append-only, post-quantum ledger." Never "blockchain", "mining", or "coin".
6. **No pixel-identical claim** — copies differ by word choice; the honest line is
   *"reads as an ordinary copy, carries a different hidden fingerprint."*
7. **Reserved colors** — green only where something was checked, red only at real
   failure or unknown. Decorative use breaks the rule.

A judge trusts the tool that discloses its own limits.

---

## 11. The three lanes (parallel work model)

The frontend contract (`web/src/design-system/contract.md`) is frozen on `main`,
then three git worktrees build in parallel without touching each other's files:

| Lane | Owns |
|---|---|
| **A** | `web/src/design-system/`, `web/src/scenes/`, `web/src/components/`, `web/src/shell/`, `App.jsx` |
| **B** | `web/src/dashboards/` (Dvārapāla, Sūchī, Anveṣaṇa, Pramāṇapatra) |
| **C** | `logfirst/authority/` glue endpoints + `web/src/api.js` |

Lanes merge in order **C → A → B**.

---

## 12. Known gaps and unwired code

Reported honestly rather than hidden:

- **Collusion is ranking-only at realistic document lengths.** The formal Tardos
  bound needs ~1201 mark positions; a long document yields ~185. The tool ranks
  suspects with scores and says so; it does not name one colluder at a stated
  false-positive rate.
- **Attribution proves key/device/session, not the human.** Stated on every result
  and stamped into every certificate.
- **The ledger is a permissioned transparency log, not Bitcoin.** Sold with the
  "everyone holds the book" image, told truthfully.
- **Corpus is template prose**; measured carrier densities are achievable, not typical.
- **Transport TLS is classical ECDSA** by design and outside the evidence path.
- **Frontend gaps:** `Pramanapatra` is not a route (launched inline);
  `src/container.js`, `src/format.js`, and most of `src/download.js` are
  implemented and tested but not yet imported by any component; several `api`
  methods are defined-but-unused; `GateScene`/`TraceScene` are unreferenced stubs;
  `StatusStrip` is mounted with placeholder metrics on every authed route (live
  polling currently exists only in the sender's `LedgerPulse`).

---

## 13. Reading order

1. This file — the map.
2. `SAKSHYA-MASTER-DESIGN-PLAN.md` — the design bible (every screen, every 3D moment, the copy, the honesty rules).
3. `SAKSHYA-FRONTEND-PLAYBOOK.md` — how to build it (anti-slop rules, themes, workflow, lanes).
4. `web/src/design-system/contract.md` — the frozen shared interface.
5. `CLAUDE.md` — the golden rules for working in this repo.

## 14. Ground rules for contributing

- **Do not touch the model's real working** (crypto, ledger, witness, watermark,
  forensics, verifier). Backend work is thin glue only.
- **Honesty rails are sacred.** Never fake "verified".
- **Air-gapped.** Zero external network calls in the frontend; only origin is
  `127.0.0.1:8443`. Vendor every dep, font, texture, model.
- **Anti-slop.** A sonar console, not a SaaS template. One accent per screen.
- **3D only where it explains something**, ~60fps on a weak laptop, every scene
  ships a static fallback.
- **Never commit. The human commits.**
