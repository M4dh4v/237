#!/usr/bin/env bash
# One command to run SĀKṢYA. No venv. Works from any directory.
#
#   ./run.sh          serve API (127.0.0.1:8443) + console (127.0.0.1:7891)
#   ./run.sh --clean  wipe the deployment, the caches and any stale process,
#                     then start over from a freshly built seed
#   ./run.sh setup    install every dependency into the current python, once
#
# The backend lives in logfirst/ and scripts/demo.py -- there is no backend/
# folder. This script cd's to the repo root itself, so "can't find demo.py"
# cannot happen regardless of where you run it from.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

PY=${PY:-python}
PIP=${PIP:-pip}
# Where the deployment lives: keys, mTLS material, ledger, anchors, witness
# state. Same default as ecosystem.config.js, so the dev run and the pm2
# deployment never disagree about which deployment they are talking to.
DATA_DIR=${DATA:-/tmp/logfirst-demo}
# Must match server.port in web/vite.config.js. It is echoed below, and a run
# that prints one address while listening on another is worse than no message.
WEB_PORT=${WEB_PORT:-7891}

case "${1:-}" in
  "")              MODE=serve ;;
  setup)           MODE=setup ;;
  --clean|clean)   MODE=clean ;;
  *) echo "usage: ./run.sh [--clean | setup]" >&2; exit 2 ;;
esac

setup() {
  echo ">> installing python deps into $($PY -c 'import sys;print(sys.executable)') (no venv)"
  $PIP install --break-system-packages -e ".[service,forensics,ocr,qr,dev]"
  echo ">> checking the environment"
  $PY scripts/check_env.py || true
}

if [ "$MODE" = setup ]; then setup; exit 0; fi

# The #1 cause of "backend not reachable": a previous run left processes alive.
# demo.py spawns witness subprocesses; a Ctrl-C that doesn't reap them leaves
# the witness ports (9101+) held, and the next backend then refuses to start.
# A stale vite holds 7891. So every run starts from a clean slate.
kill_stale() {
  pkill -f 'scripts/demo.py'   2>/dev/null || true
  pkill -f 'logfirst.witness'  2>/dev/null || true
  pkill -f 'web/node_modules/.bin/vite' 2>/dev/null || true
  pkill -f 'logfirst-web'      2>/dev/null || true
  # pkill returns as soon as the signal is *sent*, and a witness still shutting
  # down keeps its port bound -- which is exactly the state the next start
  # refuses to come up in. Wait for the processes to actually be gone, with a
  # bound so a wedged process cannot hang the run.
  for _ in $(seq 1 20); do
    pgrep -f 'scripts/demo.py|logfirst\.witness|web/node_modules/\.bin/vite' \
      >/dev/null 2>&1 || break
    sleep 0.25
  done
}

# Everything a clean run needs removed, in the order that makes it safe:
# stop the writers before deleting what they hold open.
clean_state() {
  echo ">> cleaning: stopping this project's processes"
  kill_stale
  # pm2 runs the same two processes when the console is deployed
  # (ecosystem.config.js). Stop only the apps this repo owns -- never
  # `pm2 stop all`, which would take down unrelated apps on the same daemon,
  # and (`sihfrontend` is one of those).
  if command -v pm2 >/dev/null 2>&1; then
    pm2 stop sakshya-api sakshya-ui >/dev/null 2>&1 || true
  fi

  # The deployment itself. Removing the whole directory is the same thing the
  # backend's --fresh does; doing it here too means the wipe has already
  # happened even if the backend then fails to start for another reason. It
  # also takes the RESET_REQUESTED sentinel with it, so a reset left over from
  # an earlier session cannot fire a second time.
  rm -rf "$DATA_DIR"

  # Caches and logs, so "clean" means clean rather than "mostly clean". The
  # vite cache is in node_modules and survives most of what people call a
  # restart; a stale dep-optimization cache is its own class of confusing
  # failure. pytest's cache and __pycache__ are here for the same reason.
  rm -rf web/node_modules/.vite .pytest_cache
  rm -f /tmp/sakshya-api.log /tmp/sakshya-smoke.log
  find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

  echo ">> removed $DATA_DIR, the vite/pytest caches and the api logs"
}
[ "$MODE" = clean ] && clean_state
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
#
# --fresh is passed only for --clean. On a normal run the deployment is reused
# on purpose: a restart must not throw away the ledger an operator was just
# looking at, and the console's own reset control is what asks for a rebuild.
FRESH=()
[ "$MODE" = clean ] && FRESH=(--fresh)
echo ">> starting backend ..."
$PY scripts/demo.py --serve --data "$DATA_DIR" --words "${WORDS:-1800}" \
  ${FRESH[@]+"${FRESH[@]}"} >/tmp/sakshya-api.log 2>&1 &
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

if [ "$MODE" = clean ]; then
  echo ">> clean run: rebuilt from seed, new keys, empty ledger"
fi
echo ">> API  http://127.0.0.1:8443   (up)"
echo ">> UI   http://127.0.0.1:$WEB_PORT   (Ctrl-C stops both)"
cd web && npm run dev
