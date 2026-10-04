# SĀKṢYA

Give the same secret file to many officers. Every copy reads like an ordinary
copy but quietly knows who opened it — and the record of who-opened-what is held
by many witnesses, so no single admin can rewrite it.

Offline, post-quantum, forensic-attribution instrument. (SIH26237 / WESEE.)

## Run it (demo)

Two steps. No venv, no config.

**1. First time only — install:**

```
./run.sh setup
```

**2. Every time — run:**

```
./run.sh
```

It starts both halves and prints:

- **Backend API** → http://127.0.0.1:8443
- **Frontend / console** → http://127.0.0.1:7891

Open the frontend link in your browser. Press **Ctrl-C** to stop both.

**Start over from scratch** — new keys, empty ledger, no leftover state:

```
./run.sh --clean
```

That stops anything a previous run left behind, wipes the deployment directory
(`/tmp/logfirst-demo`, or `$DATA` if you set one), clears the vite and pytest
caches, and rebuilds the deployment from its seed. A plain `./run.sh` reuses
the existing deployment on purpose, so the ledger survives a restart.

## If something's off

- **`python deps missing`** → you skipped step 1. Run `./run.sh setup`.
- **Backend not reachable** → `./run.sh` waits for the backend and clears any
  stale run before starting, so just run it again. If it prints the backend log
  and exits, read the last lines — that's the real error.
- **OCR of uploaded images does nothing** → optional, one system package:
  `sudo pacman -S tesseract-data-eng`. Everything else works without it.

## What's where

- `logfirst/` — the backend (crypto, ledger, witnesses, watermark, forensics).
- `scripts/demo.py` — the server you run.
- `web/` — the React console.
- `verifier/` — the standalone, independent evidence checker.

Tests: `python -m pytest`
