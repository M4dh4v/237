#!/usr/bin/env python3
"""Check that this machine can actually run the system, before anything runs.

    python scripts/check_env.py            # human output, exit 1 on a hard fail
    python scripts/check_env.py --json     # machine-readable

Why this exists as a program rather than three lines in the Makefile: every
dependency here fails *late* and *misleadingly*, and the whole point is to turn
those failures into one honest sentence up front.

* **liboqs.** The Python binding installs from PyPI; the native ``liboqs.so``
  does not. When the library is missing the binding still imports, and the
  failure surfaces much later as a signature that will not verify -- i.e. the
  verifier reports a tampered ledger. That is the worst possible false positive
  for this system, so it is checked by *using* each algorithm the system
  depends on rather than by importing the module.

* **tesseract.** OCR is a system binary. Without it the leak-check pipeline can
  still be imported and called; it just returns nothing useful.

* **fpdf2.** Required, not optional, and checked here rather than left to
  surface as an ImportError when the authority starts. Sealing a document
  renders it, so without fpdf2 there is no distribution path at all -- every
  ``/documents`` request fails, and the failure looks like a broken route
  rather than a missing library.

* **The optional bits.** ``qrcode`` (anchor rendering) and ``sklearn``
  (document identification) are genuinely optional, and the system is built to
  say so rather than crash: the anchor still gets written and printed as a
  short code, and the pipeline reports that identification is unavailable. They
  are reported as notes, not failures, so nobody installs a dependency the demo
  does not need in order to make a green tick appear.

Checks are reported in three levels -- ``ok``, ``note``, ``fail`` -- and only
``fail`` sets the exit status.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

OK = "ok"
NOTE = "note"
FAIL = "fail"

# The algorithms, by the names this system uses, with where each is used. Kept
# as data so the check exercises exactly what the code asks for -- a typo here
# would be caught by the check failing on a machine that is in fact fine, which
# is the safe direction.
REQUIRED_SIGS = ("ML-DSA-65", "SLH_DSA_PURE_SHA2_128S")
REQUIRED_KEMS = ("ML-KEM-768",)


def check_liboqs(results: list) -> None:
    """Import the binding, then use every algorithm the system needs."""
    try:
        import oqs
    except ImportError as e:
        hints = ["pip install liboqs-python"]
        if not os.environ.get("LD_LIBRARY_PATH"):
            hints.append(
                "and make sure the native liboqs.so is on the loader path -- "
                "the Python binding alone is not enough")
        results.append((FAIL, "liboqs-python", f"not importable: {e}", hints))
        return

    try:
        version = getattr(oqs, "__version__", "unknown")
    except Exception:                                           # noqa: BLE001
        version = "unknown"

    problems = []
    for name in REQUIRED_KEMS:
        try:
            oqs.KeyEncapsulation(name)
        except Exception as e:                                  # noqa: BLE001
            problems.append(f"KEM {name}: {e}")
    for name in REQUIRED_SIGS:
        try:
            oqs.Signature(name)
        except Exception as e:                                  # noqa: BLE001
            problems.append(f"signature {name}: {e}")

    if problems:
        results.append((
            FAIL, "liboqs",
            "the binding imported but cannot provide the required algorithms "
            "-- the native library is missing or too old ("
            + "; ".join(problems) + ")",
            [f"LD_LIBRARY_PATH is currently "
             f"{os.environ.get('LD_LIBRARY_PATH') or '(unset)'}",
             "build liboqs and point LD_LIBRARY_PATH at its lib directory",
             "see README 'Installing liboqs'"]))
        return

    results.append((
        OK, "liboqs",
        f"{version}; " + ", ".join(REQUIRED_KEMS + REQUIRED_SIGS) + " available",
        []))


def check_tesseract(results: list) -> None:
    exe = shutil.which("tesseract")
    if not exe:
        results.append((
            NOTE, "tesseract",
            "not on PATH: the leak-check pipeline can still take pasted text, "
            "but OCR of a screenshot will not work and the OCR round-trip test "
            "will fail",
            ["dnf install tesseract  /  apt install tesseract-ocr"]))
        return
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             timeout=10)
        first = (out.stdout or out.stderr).splitlines()[0].strip()
    except Exception as e:                                      # noqa: BLE001
        results.append((NOTE, "tesseract", f"present but would not run: {e}", []))
        return
    results.append((OK, "tesseract", f"{first} at {exe}", []))


def check_python(results: list) -> None:
    if sys.version_info < (3, 11):
        results.append((FAIL, "python",
                        f"{sys.version.split()[0]}; 3.11 or newer is required",
                        []))
    else:
        results.append((OK, "python", sys.version.split()[0], []))


# Required imports. Distinct from OPTIONAL below, and the distinction is the
# point: these are not degradations, they are failures, because the code that
# uses them has no fallback. Listed as data so the manifest, this check and the
# import in the tree cannot drift apart without one of them saying so.
REQUIRED_MODULES = (
    ("fpdf", "sealing renders the document, so the authority cannot seal "
             "anything and no document can be distributed"),
)


def check_required_modules(results: list) -> None:
    for mod, consequence in REQUIRED_MODULES:
        try:
            __import__(mod)
        except ImportError:
            results.append((FAIL, mod, f"missing -- {consequence}",
                            ["pip install 'fpdf2>=2.8,<3'"]))
        else:
            results.append((OK, mod, "", []))


# Optional dependencies, with what degrades without each. Named with the import
# name and the reason, so "optional" is never the whole story. Everything listed
# here is imported somewhere in the tree behind a guard that handles its
# absence; a dependency that is declared but never imported does not belong on
# this list, it belongs out of the manifest.
OPTIONAL = (
    ("qrcode", "anchors cannot be rendered as a scannable QR code; the value "
               "is still written to anchors.jsonl and printed as a short code"),
    ("sklearn", "document identification in the leak-check pipeline is "
                "unavailable, so a leak cannot be matched to a document"),
    ("PIL", "no image handling: the screenshot and OCR scenarios are "
            "unavailable"),
    ("reedsolo", "the watermark payload has no error correction, so a single "
                 "misread marker corrupts the whole pointer"),
    ("numpy", "the Tardos code cannot be evaluated at all"),
)


def check_optional(results: list) -> None:
    for mod, consequence in OPTIONAL:
        try:
            __import__(mod)
        except ImportError:
            results.append((NOTE, mod, f"missing -- {consequence}", []))
        else:
            results.append((OK, mod, "", []))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="emit the results as JSON instead of prose")
    args = ap.parse_args(argv)

    results: list = []
    check_python(results)
    check_required_modules(results)
    check_liboqs(results)
    check_tesseract(results)
    check_optional(results)

    failures = [r for r in results if r[0] == FAIL]

    if args.json:
        print(json.dumps(
            {"ok": not failures,
             "results": [{"level": lv, "name": n, "detail": d, "hints": h}
                         for lv, n, d, h in results]},
            indent=1, sort_keys=True))
        return 1 if failures else 0

    for level, name, detail, hints in results:
        mark = {OK: "  ok  ", NOTE: " NOTE ", FAIL: " FAIL "}[level]
        line = f"[{mark}] {name}"
        if detail:
            line += f": {detail}"
        print(line)
        for h in hints:
            print(f"           {h}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed. The system cannot run "
              f"correctly until these are fixed --")
        print("and note that a missing liboqs does not present as a missing "
              "library, it presents")
        print("as a signature that will not verify.")
        return 1
    notes = sum(1 for r in results if r[0] == NOTE)
    print("environment is usable." +
          (f" {notes} optional component(s) missing; each degrades a named "
           f"feature, listed above." if notes else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
