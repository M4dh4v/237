#!/usr/bin/env python3
"""Tamper with a committed ledger entry and watch every check catch it.

    python scripts/tamper_demo.py --data /tmp/logfirst-tamper --fresh

Spec deliverable: "tamper demo showing consistency proof failure against the
previously externalized root and witnesses disagreeing."

Six attacks, in increasing order of how much of the system has to be subverted
before they would work. Nothing is faked: the tamper is a real UPDATE against the
ledger's own SQLite file, the witnesses are the real witness processes answering
over HTTP, and the last step is the standalone verifier an auditor would run,
which shares no code with the server.

  1. Rewrite a committed entry.          Caught: the entry no longer folds to
                                         the root the witnesses signed.
  2. Rewrite it, rebuild the tree,      Caught: the rebuilt head is not a
     and re-sign the head with the       consistent extension of the root that
     log's own key.                      was already externalized. The attacker
                                         holds every key the server holds and it
                                         still does not help.
  3. Ask a witness to co-sign the        Caught: it already signed a different
     rebuilt root at the same size.      root at that size. Equivocation.
  4. Ask a witness to co-sign an         Caught: it will not sign a size behind
     altered head at a size below its    its high-water mark, even one it has
     high-water mark.                    no record of having signed.
  5. Ask a witness to co-sign a larger   Caught: it verifies the extension
     head with no usable proof.          against its own last root rather than
                                         trusting that a proof was supplied.
  6. Hand the result to the              Caught: the standalone verifier reports
     standalone verifier.                the witness disagreement and the
                                         anchor contradiction, by name.

Attack 1 is what a plain hash chain catches. Attacks 2 and 3 are what the
witnesses and the externalized anchor exist for. An operator who controls the
server can do attack 1 and rebuild everything the server holds -- including
re-signing the head, because in this build the log's private key sits in the same
file as the ledger (see SIMULATED below). What that operator still cannot do is
reach the root that already left the building, or find a witness willing to sign
a second, different root at a size it has already signed. Step 2's rebuilt,
correctly self-signed head is the artefact the rest of the demo runs against.

Attack 4 needs a witness whose record has a *gap* -- a size below its high-water
mark that it never signed. That is the ordinary consequence of a witness being
down while the log grew, and rather than assert it this script creates it: it
kills one witness, appends two entries while it is gone, restarts it, and
appends one more. The gap is printed from the witness's own state file.

Everything here is real except the deployment's particulars, which
``logfirst.data.scenario.SIMULATED`` lists and this script prints.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logfirst.crypto import pqc                                  # noqa: E402
from logfirst.data.scenario import SIMULATED, Scenario           # noqa: E402
from logfirst.ledger import merkle                               # noqa: E402
from logfirst.models import STH                                  # noqa: E402

CAUGHT = "caught"
MISSED = "NOT CAUGHT"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def banner(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def step(n, title: str) -> None:
    print(f"\n[{n}] {title}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="/tmp/logfirst-tamper")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--words", type=int, default=1800)
    args = ap.parse_args(argv)

    data_dir = os.path.abspath(args.data)
    print(__doc__.split("\n\n")[0])
    print("\nSimulated, and said so:")
    for s in SIMULATED:
        print(f"  * {s}")

    with Scenario.build(data_dir, n_docs=2, target_words=args.words, seed=5,
                        start_witnesses=True, min_witnesses=2,
                        fresh=args.fresh) as sc:
        recipients = sorted(sc.dep.recipients())
        doc_id = "DOC-0000"
        sc.distribute(doc_id, recipients)
        for r in recipients:
            sc.node(r).open(doc_id, mark=True)

        log = sc.log
        wids = sorted(sc.dep.witness_pubs())

        banner(f"A ledger of {log.tree_size()} entries, witness quorum "
               f"{sc.dep.min_witnesses}, witnesses {', '.join(wids)}")
        anchor = sc.authority.anchor_now()
        assert anchor is not None, "the deployment has no anchorer configured"
        anchored_size = int(anchor["tree_size"])

        step(0, "Externalize the current root, out of band")
        print(f"  size {anchored_size}  root {anchor['root_hash'][:32]}...")
        print(f"  signed {anchor['alg']}, {anchor['timestamp']}")
        print(f"  short code {anchor['short_code']}")
        print("  In the field this goes on paper, on a QR on a wall, or onto "
              "write-once")
        print("  media. What makes it evidence is only that the server cannot "
              "reach it")
        print("  afterwards, so we keep it and hold the server to it below. "
              "Note the log")
        print("  keeps growing after this: the anchor is a prefix it must "
              "still extend.")

        # -- give a witness a real gap in its record -----------------------
        print(f"\n  Before attacking anything: attack 4 needs a witness with a "
              f"hole in its")
        print(f"  record, so let us make one the way it really happens.")
        gap_wid = wids[0]
        print(f"  killing {gap_wid}; the quorum is {sc.dep.min_witnesses} of "
              f"{len(wids)}, so the")
        print(f"  log can keep growing without it")
        sc.fleet.kill([gap_wid])
        missed = []
        for r in recipients[:2]:
            missed.append(sc.node(r).open(doc_id, mark=True)["ledger_index"])
        print(f"  appended entries {missed} while {gap_wid} was down")
        sc.fleet.start(only=[gap_wid])
        sc.fleet.wait_ready(only=[gap_wid])
        for r in recipients[:1]:
            sc.node(r).open(doc_id, mark=True)
        signed_map = _witness_signed_map(sc, gap_wid)
        gap = [s for s in missed if s + 1 not in signed_map]
        print(f"  {gap_wid} is back; its record now says it signed sizes "
              f"{sorted(signed_map)}")
        print(f"  it never signed {[s + 1 for s in gap]}, which are below its "
              f"high-water mark")
        print(f"  of {max(signed_map)}. That hole is the condition attack 4 "
              f"exercises.")

        # -- 1: rewrite a committed entry ----------------------------------
        n = log.tree_size()
        victim = anchored_size // 2          # below the anchor, so it bites
        assert victim < anchored_size, "the tampered entry must precede the anchor"
        original = log.get_leaf(victim)
        witnessed = log.sth_at(victim + 1)

        step(1, f"Rewrite committed entry {victim} in the ledger's own database")
        tampered = _perturb(original)
        _write_leaf(log, victim, tampered)
        print(f"  leaf hash now {merkle.leaf_hash(tampered).hex()[:32]}...")
        print(f"  was           {merkle.leaf_hash(original).hex()[:32]}...")

        proof = log.inclusion_proof(victim)
        folds = merkle.verify_inclusion(tampered, victim, victim + 1, proof,
                                        bytes.fromhex(witnessed.root_hash))
        print(f"\n  inclusion proof against the head the witnesses signed at "
              f"size {victim + 1}")
        print(f"  ({witnessed.root_hash[:32]}...): "
              f"{'FOLDS' if folds else 'DOES NOT FOLD'}")
        print("  The witnesses' signatures over that head still verify, so the "
              "head is not")
        print("  in doubt -- the entry is. That asymmetry is the design: the "
              "witnesses")
        print("  signed a root, and this leaf is no longer in it.")
        verdict1 = CAUGHT if not folds else MISSED

        # -- 2: rebuild, and re-sign the head with the log's own key -------
        step(2, "Rebuild the tree over the altered entry and re-sign the head")
        print("  This is the attack the rest of the system exists for. The "
              "operator has")
        print("  write access to the ledger, and in this build the log's "
              "private key is in")
        print("  the same file, so it can produce a head genuinely signed by "
              "the log over")
        print("  the rewritten history. We do exactly that, so nothing below "
              "is caught by")
        print("  a signature that could have been checked anyway.")
        head = log.sth_at(n)
        _resign_sths(log, n, head.witness_sigs)
        rebuilt = log.latest_sth()
        self_ok = pqc.verify(log.log_pub, rebuilt.tbs(),
                             bytes.fromhex(rebuilt.log_sig), pqc.SIG)
        print(f"  rebuilt head root {rebuilt.root_hash[:32]}...")
        print(f"  the log's own signature over it verifies: "
              f"{'yes' if self_ok else 'NO'}")
        print(f"  re-signed {n} head(s); the witness co-signatures riding "
              f"along are still the")
        print(f"  ones over the *original* roots, because forging them means "
              f"holding the")
        print(f"  witnesses' private keys")

        aproof = merkle.consistency_proof(log.leaf_hashes(), anchored_size, n)
        consistent = merkle.verify_consistency(
            anchored_size, n, bytes.fromhex(anchor["root_hash"]),
            bytes.fromhex(rebuilt.root_hash), aproof)
        print(f"\n  consistency proof from the anchored root (size "
              f"{anchored_size}) to the rebuilt")
        print(f"  head (size {n}): {'VALID' if consistent else 'FAILS'}")
        print(f"  anchored {anchor['root_hash'][:32]}...")
        print(f"  rebuilt  {rebuilt.root_hash[:32]}...")
        print("  This is the check a rebuilt tree cannot pass. Proving the new "
              "head extends")
        print("  the old one requires the old entries to be unchanged, and the "
              "one we")
        print("  changed is in them. The server holds every key it needs to "
              "rebuild its own")
        print("  tree and re-sign its own head; what it does not have is a way "
              "to reach a")
        print("  root that has already left the building.")
        verdict2 = CAUGHT if not consistent else MISSED

        # -- 3, 4, 5: the witnesses themselves ------------------------------
        from logfirst.ledger.witnesses import WitnessClient

        w0 = WitnessClient(gap_wid,
                           f"http://127.0.0.1:{sc.dep.witness_ports[0]}")
        print(f"\n  asking witness {gap_wid} directly, over HTTP, at "
              f"{w0.base_url} --")
        print(f"  the same process the authority asks, so its refusals are the "
              f"ones that")
        print(f"  would stop a real release.")

        step(3, "Ask a witness to co-sign the rebuilt root at the same size")
        try:
            w0.cosign(n, rebuilt.root_hash, rebuilt.timestamp, [])
            print("  CO-SIGNED -- the witness attested to the rewritten "
                  "history")
            verdict3 = MISSED
        except Exception as e:                                  # noqa: BLE001
            _refusal(e)
            print("  It kept a record of what it had already signed, so a "
                  "second, different")
            print("  root at the same size is visible to it as exactly what it "
                  "is. This is")
            print("  the check that needs the witness to be a separate "
                  "process: an authority")
            print("  holding the witness keys would simply re-sign.")
            verdict3 = CAUGHT

        step(4, f"Ask {gap_wid} to co-sign an altered head at size "
                f"{gap[0] + 1}, a size it never signed")
        rollback_size = gap[0] + 1
        # A head that is genuinely smaller, with a root that is not the one the
        # log published then -- the shape of an operator showing a witness an
        # older, doctored view in the hope that it has no record to contradict.
        try:
            w0.cosign(rollback_size, "cc" * 32, witnessed.timestamp, [])
            print("  CO-SIGNED -- the witness would sign a rollback")
            verdict4 = MISSED
        except Exception as e:                                  # noqa: BLE001
            _refusal(e)
            print("  Refused on the size alone, before looking at the tree. "
                  "Its own")
            print("  high-water mark is what bounds it, not its record of "
                  "individual sizes:")
            print("  an append-only log has no legitimate reason to shrink, so "
                  "a smaller")
            print("  head is either a rollback or a server that lost data, and "
                  "both must")
            print("  stop a key release rather than produce one.")
            verdict4 = CAUGHT

        step(5, "Ask a witness to co-sign a larger head with no usable proof")
        for label, supplied in (("no proof at all", []),
                                ("a proof that does not check out", ["bb" * 32])):
            try:
                w0.cosign(rollback_size + 1000, "dd" * 32, witnessed.timestamp,
                          supplied)
                print(f"  CO-SIGNED with {label} -- the witness signed an "
                      f"unproven head")
                verdict5 = MISSED
                break
            except Exception as e:                              # noqa: BLE001
                _refusal(e)
        else:
            print("  A witness will only extend the tree it has already "
                  "signed, and it")
            print("  checks that itself with Merkle arithmetic rather than "
                  "trusting that a")
            print("  proof was supplied. Without this rule a witness would "
                  "only attest that")
            print("  some tree existed, which is close to useless.")
            verdict5 = CAUGHT

        # -- 6: the standalone verifier ------------------------------------
        step(6, "Hand the tampered ledger to the standalone verifier")
        from logfirst.forensics.export import main as export_main
        from logfirst.ledger.anchor import read_anchors

        anchors = read_anchors(sc.dep.path("anchors.jsonl"))
        bundle_path = os.path.join(data_dir, "tampered-bundle.json")
        print(f"  exporting {n} entries and {len(anchors)} externalized "
              f"anchor(s) ...")
        export_main(["--data", data_dir, "--indexes", "all",
                     "--out", bundle_path])

        cmd = [sys.executable, "-m", "verifier.verify", bundle_path]
        env = dict(os.environ)
        # liboqs is a shared library outside the default loader path in this
        # deployment. The verifier needs it to check the post-quantum
        # signatures, and a missing one would look like a failed verification.
        env.setdefault("LD_LIBRARY_PATH", "/home/madhav/_oqs/lib64")
        env["PYTHONPATH"] = ROOT
        print(f"  $ PYTHONPATH=. python -m verifier.verify "
              f"{os.path.basename(bundle_path)}")
        print("  (a separate process that imports nothing from logfirst)")
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                              cwd=ROOT)
        out = (proc.stdout or "") + (proc.stderr or "")
        for line in out.splitlines():
            if line.strip() and "faulthandler" not in line:
                print(f"    {line}")
        verdict6 = CAUGHT if proc.returncode != 0 and "NOT VERIFIED" in out \
            else MISSED

        # -- summary --------------------------------------------------------
        banner("What each attack achieved")
        rows = [
            ("1. rewrite a committed entry", verdict1),
            ("2. rebuild, re-sign the head with the log's key", verdict2),
            ("3. witness co-signs the rewritten root", verdict3),
            ("4. witness co-signs an altered head below its mark", verdict4),
            ("5. witness co-signs a larger head with no good proof", verdict5),
            ("6. standalone verifier accepts the result", verdict6),
        ]
        for label, v in rows:
            print(f"  {label:<52} {v}")
        caught = sum(1 for _, v in rows if v == CAUGHT)
        print(f"\n  {caught}/{len(rows)} caught. Anything reported {MISSED} is "
              f"a hole in the tamper evidence.")

        print("\nWhat this does not cover, stated plainly:")
        print("  * The tamper was done by a script with write access to the "
              "ledger file. In")
        print("    a real deployment that access belongs to the authority "
              "anyway, and the")
        print("    point is that it is not enough on its own -- the witnesses "
              "and the anchor")
        print("    are what make it detectable.")
        print("  * A quorum of witnesses that colludes with the operator can "
              "sign a rewritten")
        print("    history. Three independent operators in three "
              "administrative domains is the")
        print("    mitigation; three processes on one laptop, which is what "
              "this demo runs, is")
        print("    not. The deployment records the quorum it was built with, "
              "and a reader")
        print("    should check it rather than assume.")
        print("  * The anchor is only as good as the fact that somebody kept "
              "it. An")
        print("    externalized root nobody stored proves nothing, and a "
              "verifier that takes")
        print("    the anchor's public key from the same bundle is checking "
              "internal")
        print("    consistency, not authenticity -- see verify_anchor's "
              "docstring.")
        print("  * Attack 3 catches the operator only because the witnesses "
              "have their own")
        print("    record. A witness that had *not* signed that size would see "
              "the rebuilt")
        print("    root as a first-time request, which is why the quorum is "
              "three and why")
        print("    attack 4's refusal is the one that matters for the gap.")

        return 0 if caught == len(rows) else 1


def _refusal(exc: Exception) -> None:
    msg = str(exc)
    msg = msg.split("refused: ", 1)[-1] if "refused: " in msg else msg
    print(f"  refused: {msg}")


def _witness_signed_map(sc, wid: str) -> dict:
    """Read a witness's own record of what it has co-signed."""
    import json
    with open(sc.dep.path(f"{wid}.json"), "r", encoding="utf-8") as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.get("signed", {}).items()}


def _perturb(leaf: bytes) -> bytes:
    """Change one byte of a committed entry, in a field a human would read.

    The source IP is the tamper a real operator would most plausibly attempt,
    because it is the field that points at a person. Which field it is does not
    affect any check below: every one of them is over the bytes.
    """
    for needle in (b'"source_ip":"', b'"device_fp":"', b'"timestamp":"'):
        if needle in leaf:
            return leaf.replace(needle, needle + b"9", 1)
    raise SystemExit("could not find a field to tamper with; leaf was: "
                     + leaf[:200].decode("utf-8", "replace"))


def _write_leaf(log, idx: int, leaf: bytes) -> None:
    """Write an altered leaf straight into the ledger's database."""
    log.conn.execute("UPDATE leaves SET leaf_data=?, leaf_hash=? WHERE idx=?",
                     (leaf, merkle.leaf_hash(leaf), idx))
    log.conn.commit()
    log._reload_cache()                                         # noqa: SLF001


def _resign_sths(log, n: int, stale_witness_sigs: dict) -> int:
    """Re-sign every head over the rewritten tree, using the log's own key.

    The witness signatures are carried over unchanged. That is not an oversight:
    the attacker holds the log key and does not hold the witness keys, so this is
    the most complete forgery available to it. What it produces is a ledger that
    is entirely self-consistent -- the log's own signature over every head
    verifies, and each entry's inclusion proof folds to the head at its own size
    -- which is the right artefact to point the independent verifier at.
    """
    log._reload_cache()                                         # noqa: SLF001
    for size in range(1, n + 1):
        row = log.conn.execute("SELECT ts FROM sth WHERE tree_size=?",
                               (size,)).fetchone()
        if row is None:
            continue
        root = merkle.root_from_hashes(log.leaf_hashes()[:size])
        sth = STH(tree_size=size, root_hash=root.hex(), timestamp=row["ts"],
                  witness_sigs=stale_witness_sigs)
        sth.log_sig = pqc.sign(log.log_sec, sth.tbs(), pqc.SIG).hex()
        log.conn.execute("UPDATE sth SET root_hash=?, log_sig=? WHERE "
                         "tree_size=?", (root, bytes.fromhex(sth.log_sig),
                                         size))
    log.conn.commit()
    return n


if __name__ == "__main__":
    raise SystemExit(main())
