"""Export an evidence bundle, so a third party can check it without the server.

    python -m logfirst.forensics.export --data demo_data --indexes 0,1,2 \
        --out bundle.json

Then, from a checkout that trusts nothing here:

    python -m verifier.verify bundle.json
"""

from __future__ import annotations

import argparse
import sys

from ..data.deploy import Deployment
from ..ledger.anchor import read_anchors
from .bundle import BundleExporter


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="export",
        description="Export a ledger evidence bundle for independent "
                    "verification.")
    ap.add_argument("--data", required=True,
                    help="deployment directory (holds deployment.json)")
    ap.add_argument("--indexes", required=True,
                    help="comma-separated ledger indices, or 'all'")
    ap.add_argument("--out", default="bundle.json")
    ap.add_argument("--no-anchors", action="store_true",
                    help="omit externalized anchors; the verifier will then "
                         "report that consistency was not checked")
    args = ap.parse_args(argv)

    dep = Deployment(args.data)
    ledger = dep.open_log()
    n = ledger.tree_size()
    if args.indexes.strip() == "all":
        indexes = list(range(n))
    else:
        try:
            indexes = [int(x) for x in args.indexes.split(",") if x.strip()]
        except ValueError:
            print(f"--indexes must be integers or 'all', got {args.indexes!r}",
                  file=sys.stderr)
            return 2
    if not indexes:
        print(f"ledger at {args.data} is empty; nothing to export",
              file=sys.stderr)
        return 2

    anchors = [] if args.no_anchors else read_anchors(dep.path("anchors.jsonl"))
    exporter = BundleExporter.from_deployment(dep, ledger)
    bundle = exporter.save(ledger, indexes, args.out, anchors)

    print(f"wrote {args.out}: {len(bundle['entries'])} entry/entries, "
          f"{len(bundle['anchors'])} anchor(s), "
          f"quorum {bundle['witness_quorum']}, "
          f"{len(bundle['witness_pubs'])} witness key(s)")
    for w in bundle.get("warnings", []):
        print(f"warning: {w}")
    print(f"verify with: python -m verifier.verify {args.out}")
    return 0


if __name__ == "__main__":                                 # pragma: no cover
    raise SystemExit(main())
