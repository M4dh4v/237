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
- **My 10 tests pass.** Full suite: `510 passed, 4 skipped`, with the only
  15 failures + 3 errors all from one missing system package (below).
- **Frontend build passes** (`cd web && npm run build`) with the rewritten
  `api.js`.
- File handling stays local; no outbound calls.

### Only remaining failures — missing tesseract English data (one command)
Every failure/error left in the suite is OCR: `tests/test_ocr_harness.py`, the
screenshot route test, and `test_generate::test_verify_recovers_the_truth...`.
Cause: this box has no `eng.traineddata` (only `afr`/`osd` in
`/usr/share/tessdata/`). Fix, once, with root:

```
sudo pacman -S tesseract-data-eng
```

Nothing in the code can supply this offline — it is a system language pack. The
serve path and everything non-OCR run without it.

## Environment hardening (venv-free, permanent)
Recurring "no venv / missing library" startup pain is fixed at the source:
- **`Makefile`** — `PY`/`PIP`/`PYTEST` now default to the system `python`/`pip`/
  `python -m pytest` (was `.venv/bin/*`); `bootstrap` installs directly with
  `pip install --break-system-packages -e ".[...]"` (no `.venv`); `OQS_LIB`
  defaults to `$(HOME)/_oqs/lib` (was a hardcoded other-developer path).
- **`run.sh`** (new, repo root) — one command, cwd-independent:
  `./run.sh` serves API+console, `./run.sh setup` installs deps once. Fails
  fast with a fix message if deps are absent; warns (not blocks) when tesseract
  English data is missing.
- **`tests/test_verifier_independence.py`** — replaced the hardcoded
  `/home/madhav/_oqs/lib64` with an ambient-or-`$HOME/_oqs/lib` `LD_LIBRARY_PATH`
  and put the interpreter's real site directories on the child's `PYTHONPATH`,
  so the isolation subprocess finds `oqs` regardless of a reset `HOME`
  (the venv-less `pip --user` layout). This test now passes. Verifier
  independence is still enforced by the meta-path import hook, unchanged.

**Not committed — awaiting human commit.**
