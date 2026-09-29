# PROGRESS — Lane C (backend glue + api.js)

Status: **done**, pending human commit. Plan: `PLAN-lane-c.md`.

## Delivered

### Backend adapters — `logfirst/authority/demo_api.py` (all inside `register_demo_routes`)
- `POST /demo/source/upload` — multipart file → `_extract_document` (PDF text
  layer via `pypdf`, image via existing tesseract OCR, text passthrough) →
  registered as a sealable doc in `scenario.docs`. Returns `{docId, preview,
  capacity}`.
- `POST /demo/source/compose` — `{title, body}` → same registration path.
- `GET /demo/source/{id}/capacity` — `{positions, needed, strength}` from the
  existing `payload.plan_for_document`.
- `POST /demo/admin/recipients/create` — enrols via existing
  `dep.add_recipient` + `dep.sync_store(scenario.store)`; returns card
  `{recipientId, displayName, role, fingerprint, status, note}`.
- `POST /leakcheck/upload` — multipart file → per-page extraction → existing
  `investigator().investigate`. Returns the `/leakcheck` shape + `pages`.
- `POST /evidence/certificate` — `{finding_id: <ledger index>}` → existing
  `BundleExporter` → `{pdf: null, json: <verifiable bundle>, note}`.

New module-level helpers: `_extract_document`, `_slug`. No cryptography, no
watermark change, no change to what/when is committed. New docs flow through the
same seal→open→mark path as the corpus.

### Frontend — `web/src/api.js`
- Removed `DEMO_STUBS`, `mock`, `fakeHash`, `mockCapacity` and every stub branch.
- The six glue methods now call the real routes, exact frozen signatures kept,
  `ApiError`/`isFailClosed`/`isUnreachable`/`postForm` reused unchanged.
- `uploadLeak` now returns the real `/leakcheck` shape + `pages` (the P0 stub's
  looser `documentMatch`/`recipientAttribution` shape is gone — Lane B reads the
  same shape as `api.leakcheck`).

### Dependencies (pinned, in `requirements.txt` + `pyproject.toml` `service`)
- `python-multipart>=0.0.9` — FastAPI file uploads + TestClient.
- `pypdf>=4,<6` — pure-Python PDF text-layer extraction.

### Tests — appended to `tests/test_demo_api.py` (10 new, all green)
compose→distribute, upload text, upload PDF text-layer, binary-junk fails-closed,
create-recipient→listed→revoke, capacity matches `/demo/documents`, capacity 404,
leakcheck/upload identifies + reports pages, certificate bundle passes
`forensics.bundle.selfcheck`, certificate rejects a non-index.

## Verification
- **Do-not-touch modules byte-for-byte unchanged:**
  `git diff --stat -- logfirst/crypto logfirst/ledger logfirst/witness
  logfirst/watermark logfirst/forensics verifier` → empty.
- **My 10 tests pass.** Full suite minus two pre-existing environment failures:
  `508 passed, 4 skipped`.
- **Frontend build passes** (`cd web && npm run build`) with the rewritten
  `api.js`.
- File handling stays local; no outbound calls.

### Pre-existing environment failures (NOT caused by Lane C)
1. `tests/test_ocr_harness.py` (+ the screenshot route test and
   `test_generate::test_verify_recovers_the_truth_from_the_artefacts`) fail
   because this machine has **no `eng.traineddata`** for tesseract
   (`/usr/share/tessdata/` has `afr`/`osd` only). Fix: install the English
   language pack (Arch: `sudo pacman -S tesseract-data-eng`).
2. `tests/test_verifier_independence.py::test_verify_runs_with_logfirst_unimportable`
   fails on a **hardcoded `LD_LIBRARY_PATH: /home/madhav/_oqs/lib64`** (line 196)
   — a machine-specific path committed for a different developer; this box has
   liboqs at `/home/void/_oqs/lib`.

Both are unrelated to the glue and untouched by this lane.

## Environment note (this machine)
No `.venv` was present and system Python lacked the deps, so they were installed
with `pip --break-system-packages` (Arch PEP 668): the full `requirements.txt`
plus `pypdf`/`python-multipart`, and `liboqs-python` was built from source
(needed a `cmake` wheel). The normal path is `make bootstrap` into `.venv`.

**Not committed — awaiting human commit.**
