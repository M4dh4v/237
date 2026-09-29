#!/usr/bin/env python3
"""Run the demo: witnesses up, authority serving, a corpus ready to distribute.

    python scripts/demo.py --serve            # then open the front end
    python scripts/demo.py --scripted         # no browser: walk the whole story

Two modes, and the difference matters.

``--serve`` builds a deployment, starts the witness processes, and serves the
authority's API on 127.0.0.1:8443 without TLS, so the Vite dev server can proxy
to it. TLS and mTLS are how a real deployment runs and ``--tls`` uses them, but
a browser talking to a self-signed mTLS endpoint is a certificate-import
exercise that has nothing to do with the system being demonstrated. The flag
says so on stdout rather than letting anyone mistake the plain-HTTP run for the
real transport.

``--scripted`` does not serve anything. It drives the same objects in order and
prints what happens, including the parts that are supposed to fail: a witness
killed mid-open so the authority fails closed and releases no key, and a
spliced copy so the Tardos channel is what carries the evidence. A demo that
only shows the happy path is a demo of a different system.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logfirst.data.scenario import SIMULATED, Scenario      # noqa: E402

BANNER = """
logfirst -- log-first, post-quantum, recipient-attributable distribution
========================================================================
A document cannot be decrypted until the recipient's own signature is committed
to a Merkle transparency ledger co-signed by independent witnesses. The
watermark on the copy they keep is derived from that exact entry.

What this demo does NOT simulate away:
  * ML-KEM-768 / ML-DSA-65 / SLH-DSA key generation, signing and verification
  * the ledger append, the witness quorum, and the fail-closed ordering
  * the linguistic watermark and the OCR round trip

What it does simulate, and says so:
"""


def _print_simulated() -> None:
    for s in SIMULATED:
        print(f"  * {s}")
    print()


def serve(args) -> int:
    data_dir = os.path.abspath(args.data)
    sc = Scenario.build(data_dir, n_docs=args.docs, target_words=args.words,
                        seed=args.seed, start_witnesses=True,
                        min_witnesses=args.witnesses,
                        fresh=args.fresh)
    _print_simulated()
    print(f"deployment: {data_dir}")
    print(f"witnesses:  {len(sc.dep.witness_ports)} processes on "
          f"{sc.dep.witness_ports}, quorum {sc.dep.min_witnesses}")
    print(f"recipients: {', '.join(sorted(sc.dep.recipients()))}")
    print(f"documents:  {len(sc.docs)}")
    print()
    if args.no_tls:
        print("WARNING: serving plain HTTP. mTLS and the app-layer signature are "
              "both part of the design; the request signature is still enforced, "
              "the transport binding is not.")
    print(f"API:        http://127.0.0.1:{args.port}")
    if not args.no_tls:
        print(f"            https://127.0.0.1:{args.port} (mTLS, client cert "
              f"required)")
    print("front end:  cd web && npm run dev   (http://localhost:5173)")
    print()

    from logfirst.authority.server import build_app

    app = build_app(sc.authority, scenario=sc)
    try:
        if args.no_tls:
            import uvicorn

            uvicorn.run(app, host=args.host, port=args.port,
                        log_level="warning")
        else:
            import uvicorn

            from logfirst.crypto.mtls import MTLSFactory

            factory = MTLSFactory.open(sc.dep.path("mtls"))
            srv = factory.issue("authority", sc.dep.path("mtls"), server=True)
            uvicorn.run(app, host=args.host, port=args.port,
                        log_level="warning",
                        ssl_certfile=srv["cert"], ssl_keyfile=srv["key"],
                        ssl_ca_certs=factory.ca_path, ssl_cert_reqs=2)
    except KeyboardInterrupt:
        pass
    finally:
        sc.close()
        print("witnesses stopped")
    return 0


def _write_artifacts(out_dir: str, doc_id: str, package: dict,
                     out: dict) -> list[tuple[str, str]]:
    """Write the files the browser would download, and describe each honestly.

    The demo should leave real artefacts on disk rather than only printing about
    them, because the claim being made -- "this file does not open without the
    server" -- is one a reader can check with `file` and `grep` in ten seconds,
    and only if there is a file to point at.

    Returns ``(path, note)`` pairs for the caller to print.
    """
    import hashlib
    from datetime import datetime, timezone

    from logfirst import pdfdoc, sealed

    os.makedirs(out_dir, exist_ok=True)
    written: list[tuple[str, str]] = []

    blob = sealed.pack(package)
    container = os.path.join(out_dir, f"{doc_id}.lfdoc")
    with open(container, "wb") as fh:
        fh.write(blob)
    written.append((container,
                    f"{len(blob):,} bytes, and not a PDF: no viewer opens it and "
                    f"%PDF occurs nowhere inside it. It is the document "
                    f"encrypted under a key only the authority can unwrap."))

    canonical = os.path.join(out_dir, f"{doc_id}-distributed.pdf")
    pdfdoc.write_pdf(canonical, out["distribution_pdf"])
    written.append((canonical,
                    f"{len(out['distribution_pdf']):,} bytes, the document as "
                    f"sealed. Not marked, because at distribution there was no "
                    f"ledger entry to derive a mark from."))

    marked_text = out.get("marked_text")
    if marked_text and (out.get("marking_plan") or {}).get("ok"):
        rendered = pdfdoc.render(
            marked_text, doc_id=doc_id,
            classification=out.get("classification") or "UNCLASSIFIED",
            created=datetime.now(timezone.utc),
            recipient_id="carol", ledger_index=out["ledger_index"],
            leaf_hash=out["leaf_hash"])
        path = os.path.join(out_dir, f"{doc_id}-carol-marked.pdf")
        pdfdoc.write_pdf(path, rendered.data)
        written.append((path,
                        f"{rendered.pages} pages, sha256 "
                        f"{hashlib.sha256(rendered.data).hexdigest()[:16]}..., "
                        f"bound to ledger entry #{out['ledger_index']}. Print "
                        f"it, pdftotext it, retype a paragraph: it still "
                        f"points back at that entry."))
    return written


def scripted(args) -> int:
    """Walk the whole story in one process, with the failures included."""
    from logfirst.data.scenario import Scenario as _S

    _print_simulated()
    data_dir = os.path.abspath(args.data)
    with _S.build(data_dir, n_docs=3, target_words=args.words, seed=args.seed,
                  start_witnesses=True, min_witnesses=args.witnesses,
                  fresh=args.fresh) as sc:
        docs = sc.docs
        recipients = sorted(sc.dep.recipients())
        doc_id = docs[0]["doc_id"]

        print(f"[1] distribute {doc_id} to {', '.join(recipients)}")
        package = sc.authority.seal(docs[0]["text"], doc_id,
                                    docs[0]["classification"], recipients)
        print(f"    sealed to the authority's KEM key; doc_hash "
              f"{package['doc_hash'][:16]}...")
        print("    no recipient key was used, and no recipient holds a share "
              "of the content key\n")

        print("[2] carol opens it; the ledger entry comes first")
        out = sc.node("carol").open(doc_id, mark=True)
        idx = out["ledger_index"]
        sth = out["sth"]
        print(f"    ledger index {idx}, leaf {out['leaf_hash'][:16]}...")
        print(f"    tree size {out['tree_size']}, root "
              f"{sth['root_hash'][:16]}...")
        print(f"    witnesses that co-signed this head: "
              f"{', '.join(sorted(sth['witness_sigs']))}")
        print(f"    watermark seed {out['watermark_seed'][:16]}... "
              f"(= HKDF of the leaf hash above)")
        print("    the key was released only after the quorum; see "
              "README 'Fail-closed ordering'\n")

        print("[3] what the mark changed")
        marked = out["marked_text"]
        diff = [(i, a, b) for i, (a, b) in
                enumerate(zip(docs[0]["text"].split(), marked.split()))
                if a != b]
        print(f"    {len(diff)} word(s) substituted, e.g. "
              + "; ".join(f"{a} -> {b}" for _, a, b in diff[:4]))
        print(f"    plan: {out['marking_plan']['pointer_bits']} pointer bits + "
              f"{out['marking_plan']['tardos_bits']} Tardos positions "
              f"({out['marking_plan']['guarantee']})\n")

        print("[3b] the files a recipient ends up with")
        artifacts = _write_artifacts(os.path.join(data_dir, "artifacts"), doc_id,
                                     package, out)
        for path, note in artifacts:
            print(f"    {path}")
            print(f"        {note}")
        print()

        print("[4] the leak-check pipeline, on carol's marked copy")
        inv = sc.investigator().investigate(leaked_text=marked)
        print(f"    status: {inv.status}")
        print(f"    document confidence {inv.doc_confidence:.3f}   "
              f"watermark confidence {inv.watermark_confidence:.3f}")
        print(f"    candidates: "
              + ", ".join(f"{c.recipient_id} ({c.source})"
                          for c in inv.candidates[:4]))
        if inv.verification:
            v = inv.verification
            print(f"    verified: {v['verified']} "
                  f"(signature {v['request_signature_ok']}, "
                  f"inclusion {v['inclusion_ok']}, "
                  f"head {v['sth_signature_ok']}, "
                  f"witnesses {len(v['witnesses_ok'])} ok / "
                  f"{len(v['witnesses_bad'])} bad)")
        print(f"    caveat: {inv.caveat[:96]}...\n")

        print("[5] an unmarked copy: the honest fallback")
        inv2 = sc.investigator().investigate(leaked_text=docs[0]["text"])
        print(f"    status: {inv2.status} (watermark recovered: "
              f"{inv2.watermark_recovered})")
        print(f"    the ledger records {len(inv2.ledger_sessions)} decryption(s) "
              f"of this document: "
              + ", ".join(s["recipient_id"] for s in inv2.ledger_sessions))
        print("    that is corroborating evidence, not an attribution, and the "
              "status says so\n")

        print("[6] two recipients splice their copies")
        other = next(r for r in recipients if r != "carol")
        coll = sc.leak_collusion("carol", other, doc_id, seed=11)
        inv3 = sc.investigator().investigate(leaked_text=coll["leaked_text"])
        print(f"    {coll['positions_differing']} positions differed between "
              f"the two copies and could be mixed")
        print(f"    status: {inv3.status}")
        print(f"    ranked: "
              + ", ".join(f"{c.recipient_id} ({c.tardos_score:.1f} vs "
                          f"threshold {c.tardos_threshold:.1f})"
                          for c in inv3.candidates[:4]))
        print(f"    guarantee: {inv3.guarantee} -- at this document length the "
              f"code ranks suspects but does not meet the formal accusation "
              f"bound\n")

        print("[7] kill the witnesses, then try to open again")
        ids = sorted(sc.dep.witness_pubs())
        sc.fleet.kill(ids)
        time.sleep(0.6)
        try:
            sc.node("bob").open(doc_id, mark=True)
            print("    !! the open SUCCEEDED with no witnesses alive -- the "
                  "fail-closed ordering is broken")
        except Exception as e:                          # noqa: BLE001
            print(f"    refused: {type(e).__name__}: {str(e)[:120]}")
            print("    no key material was produced. This is the design, not a "
                  "mishap.")
        try:
            sc.fleet.start()
        except Exception as e:                          # noqa: BLE001
            print(f"    (could not restart witnesses: {e})")
        print()

        print("[8] externalize the root")
        rec = sc.authority.anchor_now()
        if rec:
            from logfirst.ledger.anchor import ascii_qr

            print(f"    size {rec['tree_size']} root {rec['root_hash'][:24]}...")
            print(f"    signed with SLH-DSA-SHA2-128s, anchored at "
                  f"{rec['timestamp']}")
            try:
                for line in ascii_qr(rec).splitlines()[:6]:
                    print("    " + line)
            except Exception:                           # noqa: BLE001
                print("    (qrcode not installed; anchor record still written)")
            print()

        print("Evidence bundle for independent verification:")
        print(f"    python -m logfirst.forensics.export --data {data_dir} "
              f"--indexes all --out bundle.json")
        print("    python -m verifier.verify bundle.json")
        print("  (run the second from a checkout that trusts nothing here)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="demo-data")
    ap.add_argument("--docs", type=int, default=6)
    ap.add_argument("--words", type=int, default=1800)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--witnesses", type=int, default=2,
                    help="quorum size (three witness processes always run)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--fresh", action="store_true",
                    help="wipe the deployment directory first")
    ap.add_argument("--tls", dest="no_tls", action="store_false", default=True,
                    help="serve over mTLS instead of plain HTTP")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--serve", action="store_true",
                      help="serve the API for the front end")
    mode.add_argument("--scripted", action="store_true",
                      help="walk the whole story in the terminal, no server")
    args = ap.parse_args(argv)

    print(BANNER, end="")
    if args.scripted:
        return scripted(args)
    return serve(args)


if __name__ == "__main__":
    raise SystemExit(main())
