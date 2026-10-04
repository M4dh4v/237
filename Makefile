# logfirst -- log-first, post-quantum, recipient-attributable distribution.
#
# Targets are grouped by what you are trying to do, not by what they run:
#   bootstrap   get the environment to the point where anything else works
#   demo        the two things worth looking at
#   test        prove it
#   verify      the independent checks, by hand
#
# Nothing here is required to *use* the system -- every target is a thin wrapper
# over a documented command, so you can always see and run the command itself.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# No venv. Deps are installed straight into the system/user interpreter (see
# `make bootstrap`), so every target runs against plain `python`. Override any
# of these on the command line if you do want a venv: `make test PY=.venv/bin/python`.
PY      ?= python
PIP     ?= pip
PYTEST  ?= python -m pytest

DATA    ?= /tmp/logfirst-demo
TAMPER  ?= /tmp/logfirst-tamper
DATASET ?= /tmp/logfirst-dataset
WORDS   ?= 1800

# liboqs ships as a shared library that is not on the default loader path in
# this deployment. The standalone verifier needs it to check the post-quantum
# signatures, and without it the failure looks like a failed verification
# rather than a missing dependency -- which is the worst possible way for this
# particular tool to fail. Export it for everything that shells out.
OQS_LIB ?= $(HOME)/_oqs/lib
export LD_LIBRARY_PATH := $(OQS_LIB):$(LD_LIBRARY_PATH)

.PHONY: help bootstrap check-liboqs check-tesseract demo demo-scripted demo-serve \
        tamper generate verify test test-fast test-crypto test-ledger clean

help:
	@echo "logfirst"
	@echo
	@echo "  make bootstrap      install deps into the current python, check liboqs and tesseract"
	@echo "  make demo           the eight-step scripted walkthrough, with failures"
	@echo "  make demo-serve     serve the API and the console together (see below)"
	@echo "  make tamper         tamper with a committed entry; watch every check catch it"
	@echo "  make generate       write a synthetic deployment and an evidence bundle"
	@echo "  make verify         re-check that bundle with the standalone verifier"
	@echo "  make test           the whole suite (~3 min; it stands up real processes)"
	@echo "  make test-fast      everything except the OCR, HTTP and collusion measurements"
	@echo
	@echo "  DATA=$(DATA)  DATASET=$(DATASET)  WORDS=$(WORDS)  OQS_LIB=$(OQS_LIB)"

# ---------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------

# Direct install into the current interpreter -- no venv. `--break-system-packages`
# is what a PEP-668 "externally-managed" distro (Arch, recent Debian/Ubuntu) needs
# to allow this; it is a no-op on distros that don't mark themselves managed.
bootstrap:
	$(PIP) install -q --break-system-packages -e ".[service,forensics,ocr,qr,dev]"
	@$(PY) scripts/check_env.py

# liboqs is the one dependency that cannot be installed from PyPI, and the one
# whose absence produces a *misleading* failure: the Python binding imports
# fine and the error appears later as a signature that does not verify -- i.e.
# the verifier reports a tampered ledger. See scripts/check_env.py, which is a
# program rather than a recipe line precisely so it can exercise each algorithm
# instead of just importing the module.
check-liboqs:
	@$(PY) scripts/check_env.py

check-tesseract:
	@command -v tesseract >/dev/null 2>&1 || { \
	  echo "tesseract is not installed. The leak-check pipeline OCRs images, so"; \
	  echo "  the OCR round-trip test needs the system binary, not just the Python"; \
	  echo "  binding.  dnf install tesseract   /   apt install tesseract-ocr"; \
	  exit 1; }
	@echo "tesseract: $$(tesseract --version 2>&1 | head -1)"

# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

# The scripted run is the one to show someone: it walks the whole lifecycle and
# deliberately fails at two points, because a demo where nothing is ever refused
# is not evidence that anything is being checked.
demo:
	$(PY) scripts/demo.py --scripted --data $(DATA) --words $(WORDS) --fresh

# Plain HTTP on purpose. The browser cannot satisfy a client certificate, so
# mTLS would lock the front end out of its own API; the WARNING it prints says
# so. The wire format is the same either way.
#
# Two processes, because there is no bundled server for the console: the API
# binds 8443 and Vite serves the UI on 7891 (vite.config.js server.port),
# proxying the API paths to it. The API is backgrounded and killed on exit, so
# Ctrl-C stops both.
#
# What this target used to do was build web/dist and then serve the API alone,
# advertising port 8000 -- which nothing has ever listened on, since the console
# is Vite on 7891 and the API's default is 8443. The front end was therefore
# unreachable through the only documented command for starting it. (TLS was not
# the problem: plain HTTP is `demo.py --serve`'s default, and `--tls` is the
# opt-in.)
demo-serve:
	@test -d web/node_modules || (cd web && npm install --silent)
	@echo "API on 127.0.0.1:8443, console on http://127.0.0.1:7891"
	@echo "(Ctrl-C stops both.)"
	@set -e; \
	 $(PY) scripts/demo.py --serve --data $(DATA) --words $(WORDS) & \
	 api=$$!; \
	 trap 'kill $$api 2>/dev/null || true' EXIT INT TERM; \
	 cd web && npm run dev

tamper:
	$(PY) scripts/tamper_demo.py --data $(TAMPER) --words $(WORDS) --fresh

# ---------------------------------------------------------------------------
# synthetic data and independent verification
# ---------------------------------------------------------------------------

# A complete synthetic deployment: corpus, identities, real open sessions, real
# marked copies, leak artefacts, and an evidence bundle. `--verify` runs the
# leak-check pipeline over every generated leak afterwards and exits non-zero if
# any is not recovered -- a miss is a result worth seeing, not a crash.
#
# Kept separate from $(DATA) because the demo's scenario deployment and the
# generated dataset are different things built by different code, and pointing
# them at one directory makes each one's leftovers look like the other's bug.
generate:
	$(PY) -m logfirst.data.generate --out $(DATASET) --docs 8 --words $(WORDS) --verify

# Run against the bundle `generate` just wrote. This is the check that matters:
# it does not import logfirst, so it cannot be fooled by the code that produced
# the evidence. Deliberately a separate target from `generate` so the two halves
# can be run at different times, from different directories, or by different
# people.
verify: $(DATASET)/evidence-bundle.json
	$(PY) -m verifier.verify $(DATASET)/evidence-bundle.json

$(DATASET)/evidence-bundle.json:
	@echo "no bundle at $@ -- run 'make generate' first" >&2
	@exit 1

# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

test:
	$(PYTEST) -q

# The suite's cost is in three places: OCR (real tesseract on rendered images),
# the HTTP tests (real witness processes on real sockets) and the collusion
# measurements (real opens and real traces). This skips all three. It is a
# convenience for the edit-run loop, not a substitute -- CI and any claim about
# correctness run the full suite.
test-fast:
	$(PYTEST) -q --ignore=tests/test_ocr_harness.py \
	              --ignore=tests/test_authority_http.py \
	              --ignore=tests/test_collusion_indicator.py

# The primitives, which are the only things whose failure invalidates everything
# above them: the post-quantum signatures and KEM against known-answer vectors,
# and the Merkle arithmetic against the RFC 6962 vectors.
test-crypto:
	$(PYTEST) -q tests/test_crypto_kat.py tests/test_merkle.py \
	              tests/test_verifier_merkle.py

test-ledger:
	$(PYTEST) -q tests/test_witness_rules.py tests/test_ledger_failclosed.py \
	              tests/test_verifier_bundle.py tests/test_verifier_independence.py \
	              tests/test_tamper_demo.py

clean:
	rm -rf $(DATA) $(TAMPER) $(DATASET) .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
