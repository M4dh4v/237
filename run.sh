#!/usr/bin/env bash
# One command to run SĀKṢYA. No venv. Works from any directory.
#
#   ./run.sh          serve API (127.0.0.1:8443) + console (127.0.0.1:5173)
#   ./run.sh setup    install every dependency into the current python, once
#
# The backend lives in logfirst/ and scripts/demo.py -- there is no backend/
# folder. This script cd's to the repo root itself, so "can't find demo.py"
# cannot happen regardless of where you run it from.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PY=${PY:-python}
PIP=${PIP:-pip}

setup() {
  echo ">> installing python deps into $($PY -c 'import sys;print(sys.executable)') (no venv)"
  $PIP install --break-system-packages -e ".[service,forensics,ocr,qr,dev]"
  echo ">> checking the environment"
  $PY scripts/check_env.py || true
}

if [ "${1:-}" = "setup" ]; then setup; exit 0; fi

# The #1 cause of "backend not reachable": a previous run left processes alive.
# demo.py spawns witness subprocesses; a Ctrl-C that doesn't reap them leaves
# the witness ports (9101+) held, and the next backend then refuses to start.
# A stale vite holds 5173. So every run starts from a clean slate.
kill_stale() {
  pkill -f 'scripts/demo.py'   2>/dev/null || true
  pkill -f 'logfirst.witness'  2>/dev/null || true
  pkill -f 'web/node_modules/.bin/vite' 2>/dev/null || true
  pkill -f 'logfirst-web'      2>/dev/null || true
  sleep 1
}
kill_stale

# Fail fast with a fix, not a stack trace, if the deps aren't there yet.
if ! $PY -c 'import fastapi, oqs, fpdf, pypdf, multipart' 2>/dev/null; then
  echo "!! python deps missing. Run once:  ./run.sh setup" >&2
  exit 1
fi

# OCR needs the English language pack; it's the one thing this script can't
# install for you (system package, needs root). Warn, don't block -- only the
# image/screenshot leak-check path uses it.
if ! find /usr/share/tessdata /usr/share/tesseract* -name 'eng.traineddata' 2>/dev/null | grep -q .; then
  echo "   note: tesseract English data absent -> OCR of images is skipped."
  echo "         install once with:  sudo pacman -S tesseract-data-eng"
fi

[ -d web/node_modules ] || (echo ">> installing web deps" && cd web && npm install --silent)

# Start the backend and its witnesses, then WAIT until it actually answers
# before bringing up the console -- otherwise the browser loads first, can't
# reach the API, and shows "backend not reachable" until you reload.
echo ">> starting backend ..."
$PY scripts/demo.py --serve --data "${DATA:-/tmp/logfirst-demo}" --words "${WORDS:-1800}" >/tmp/sakshya-api.log 2>&1 &
api=$!
trap 'kill $api 2>/dev/null || true; pkill -f "logfirst.witness" 2>/dev/null || true' EXIT INT TERM

if ! $PY - <<'PY'
import urllib.request, time, sys
for _ in range(60):                      # up to ~30s
    try:
        urllib.request.urlopen("http://127.0.0.1:8443/health", timeout=1).read()
        sys.exit(0)
    except Exception:
        time.sleep(0.5)
sys.exit(1)
PY
then
  echo "!! backend did not come up. Its log:" >&2
  tail -n 20 /tmp/sakshya-api.log >&2
  exit 1
fi

echo ">> API  http://127.0.0.1:8443   (up)"
echo ">> UI   http://127.0.0.1:5173   (Ctrl-C stops both)"
cd web && npm run dev
