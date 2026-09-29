# PLAN — Lane C (backend glue + api.js)

Scope: SIH26237 / SĀKṢYA. Thin adapter routes in `logfirst/authority/demo_api.py`
that feed **existing** pipeline functions, plus the matching real `web/src/api.js`
methods. No new crypto, no new watermark channel, no change to what/when gets
committed. Do-not-touch modules (§13.1) stay byte-for-byte unchanged; `git diff`
will prove it.

## What I read
- Design plan §13 (all of it), `demo_api.py`, `web/src/api.js`, `contract.md` §2.
- Pipeline entry points I will feed: `scenario.docs` / `scenario.doc()`,
  `scenario.authority.seal()`, `scenario.investigator().investigate()`,
  `dep.add_recipient()` + `dep.sync_store()`, `watermark.payload.plan_for_document()`,
  `watermark.linguistic.slot_count()`, `watermark.ocr.bytes_to_image/image_to_text`,
  `forensics.bundle.BundleExporter` (for the optional certificate).

## Environment facts that shape the plan
- `tesseract` binary present; `pillow`, `fpdf2`, `pytesseract` installed.
- **Not installed:** `python-multipart` (FastAPI needs it for file uploads and
  `TestClient` needs it for the upload tests) and any PDF-reader library
  (`pypdf`/`pdfminer`/`pymupdf` all absent). `fpdf2` only *writes* PDFs.
- Air-gapped rule is about the **frontend** (no CDN/fonts). Backend pip deps are
  fine when pinned and installed at setup, same as the existing four.

### New backend dependencies (must be approved)
1. `python-multipart` — to accept `multipart/form-data` uploads for methods 1 & 4.
2. `pypdf` — pure-Python, MIT, to extract a PDF's text layer.

Both pinned, added to `requirements.txt` and `pyproject.toml`. If you'd rather add
**zero** deps, the alternative is: send files as base64 in JSON (reuses the
existing `image_b64` convention and the tested JSON error path, drops
`python-multipart`), and drop PDF text-layer support to "OCR the rasterised
pages" — but we have no rasteriser either, so PDFs would degrade to
"paste the text." **My recommendation: add both deps** — it is the honest,
conventional path and keeps large PDFs off a 33%-bloat base64 round-trip.

## Endpoints (all in `demo_api.py`, inside `register_demo_routes`)

### 1. `POST /demo/source/upload` (multipart: `file`, optional `title`)
- Sniff type from filename/content:
  - `.txt/.md/text/*` → decode UTF-8, pass through.
  - image (`png/jpg/...`) → `ocr.image_to_text(ocr.bytes_to_image(bytes))`
    (the existing tesseract path; 400 with the existing shape if OCR unavailable).
  - `.pdf` → `pypdf` text layer, page by page. Pages with no text layer are
    reported honestly (`"no text layer (scanned-PDF OCR not available in this
    build)"`) rather than silently dropped — we have no PDF rasteriser.
- Register the extracted body as a **new sealable document**: mint a doc id
  (`SRC-<8 hex>`), append `{"doc_id","text","classification","slots","words"}`
  to `scenario.docs` (in-memory list; this is exactly what `/demo/distribute`
  and the investigator read — pure glue, no model change).
- Capacity from the **existing** `payload.plan_for_document(linguistic.slot_count(text), n_users, colluders, eps)`.
- Return `{ "docId", "preview" (first ~280 chars), "capacity": {positions:
  tardos_bits, needed: tardos_required, strength: guarantee-string} }`.
- Empty/undecodable body → 400 with the existing `{"detail": ...}` shape.

### 2. `POST /demo/source/compose` (JSON `{title, body}`)
- Same registration + capacity path as #1; body passes straight through.
- Return the same `{docId, preview, capacity}` shape.

### 3. `POST /demo/admin/recipients/create` (JSON `{display_name, role?}`)
- Enroll via the **existing** `dep.add_recipient(rid, role)` (which calls the
  existing `ca.enroll_recipient` → real PQC keypair) then `dep.sync_store(store)`
  so the authority's store learns the cert (mirrors how the deployment bootstraps).
- `rid` derived from display name (slugged) + short random suffix to stay unique.
- Return card data matching the store's `/demo/admin/recipients` vocabulary:
  `{ "recipientId", "displayName", "role", "fingerprint" (cert serial or sig-pub
  hex, in mono), "status": "active" }`. Companion to existing revoke/reinstate.
- Note in the response: new recipient is enrolled but **not** in the Tardos user
  order (that list is frozen at deploy for index-stability, §scenario), so it can
  receive/open but is out of scope for collusion indexing — stated honestly, not
  hidden.

### 4. `POST /leakcheck/upload` (multipart: `file`)
- Extract text per page exactly as #1 (pdf text layer / image OCR / text
  passthrough), concatenate, then run the **existing, unchanged**
  `scenario.investigator().investigate(leaked_text=...)`.
- Return the **same shape as `/leakcheck`** (`Investigation.as_dict()` +
  `"simulated"`) plus `"pages": [{page, extraction: "text-layer"|"ocr"|"none",
  chars}]`. (Contract §2 says "same shape as `api.leakcheck` result, with
  per-page extraction status"; the P0 stub's looser shape is replaced by this.)
- Multi-page supported via `pypdf` page iteration.

### 5. (optional, cheap) `GET /demo/source/{id}/capacity`
- Look the doc up in `scenario.docs`, recompute `plan_for_document`, return
  `{positions, needed, strength}`. 404 (existing shape) if unknown id.

### 6. (optional, NOT pure glue — decision needed) `POST /evidence/certificate`
- There is no server-side "finding" store, so `findingId` has nothing to resolve
  against as written. Honest options:
  - **(a) Defer** — leave `api.certificate` returning its stub, keep the TODO.
    Cleanest for now; means `DEMO_STUBS` can't be fully deleted (one method stays
    mocked).
  - **(b) Thin JSON bundle** — accept the finding's ledger index/indexes and call
    the existing `forensics.bundle.BundleExporter` to produce the
    independently-verifiable JSON bundle; return `{json: bundle, pdf: null}` with
    a note that human-readable PDF rendering is a later presentation step. Real
    glue over existing forensics, no new proof logic.
  - **(c) Full** — (b) plus render a Pramāṇapatra PDF. More presentation code;
    largest diff.
- **My recommendation: (b).** It lets `DEMO_STUBS` be removed entirely, is real
  glue, and defers only the cosmetic PDF. **Please pick (a)/(b)/(c).**

## `web/src/api.js` changes
- Delete `DEMO_STUBS`, `mock`, `fakeHash`, `mockCapacity` and the stub branches.
- Wire the six methods to the real routes, keeping the **exact frozen signatures**
  and the `ApiError`/`isFailClosed`/`isUnreachable` contract:
  - `uploadSource(file, opts)` → `postForm('/demo/source/upload', fd)`.
  - `composeSource({title, body})` → `post('/demo/source/compose', ...)`.
  - `createRecipient({displayName, role})` → `post('/demo/admin/recipients/create', {display_name, role})`.
  - `uploadLeak(file, opts)` → `postForm('/leakcheck/upload', fd)`.
  - `sourceCapacity(docId)` → `get('/demo/source/{id}/capacity')`.
  - `certificate(findingId)` → per the #6 decision.
- `postForm`, `request`, `readDetail` already handle the fail-closed/unreachable
  contract; reused unchanged.

## Honesty rails (sacred, §2 rules)
- Uploaded/composed docs flow through the **same** seal→open→mark path; not a
  special case downstream.
- Capacity `strength` is the raw `guarantee` string (`formal`/`ranking-only`/
  `none`) — never upgraded to a friendlier word.
- New-recipient Tardos caveat stated, not hidden.
- Every route fails closed with the existing `{"detail": ...}` shape; 503s keep
  the `fail-closed` wording `isFailClosed` matches.
- Nothing an upload contains leaves the machine (§13.4).

## Tests (kept minimal, added to `tests/test_demo_api.py`)
- upload text → sealable doc id + capacity; then `/demo/distribute` accepts it.
- compose → same.
- create recipient → appears in `/demo/admin/recipients`, then revoke works.
- `/leakcheck/upload` of a rendered leaked page → identifies the doc, carries
  `pages`.
- capacity GET matches `/demo/documents` numbers for the same doc.
- (if #6 = b) certificate returns a bundle that `forensics.bundle.selfcheck`
  passes.

## Verification (before "done")
- `python -m pytest` green.
- `git diff --stat` shows **no** changes under `logfirst/{crypto,ledger,witness,
  watermark,forensics}` or `verifier/` — only `demo_api.py`, `web/src/api.js`,
  `requirements.txt`, `pyproject.toml`, tests, and this plan / `PROGRESS-lane-c.md`.
- File handling stays local; no outbound calls.
- Update `PROGRESS-lane-c.md`.
- **I do not commit. You commit.**

## Decisions (locked)
1. **Add `python-multipart` + `pypdf`** (pinned, in requirements/pyproject). Approved.
2. **Certificate = option (b): thin JSON bundle** over `BundleExporter`, `pdf:null`
   with a note; `DEMO_STUBS` removed entirely. Approved.
