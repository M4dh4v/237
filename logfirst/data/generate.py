"""Generate a synthetic deployment: corpus, identities, sessions and leaks.

This exists to answer the question "does any of this work at more than one
document and one recipient?" with data rather than with an assertion. It builds
a real deployment -- three witness processes on real sockets, a real CA, real
recipients -- drives real open sessions through the real authority, and writes
out everything a reader needs to re-run the leak check themselves.

What is generated and what is real
----------------------------------
The *prose* is synthetic, and it is honest about being synthetic in a way that
matters: :mod:`logfirst.data.corpus` builds sentences from a small frame
vocabulary precisely so that some words have known synonyms and others do not.
A corpus of natural text would have an unknown and unmeasurable carrier density,
and every capacity number downstream would be a guess wearing a measurement's
clothes.

Everything else is a real output of real code:

* certificates are issued by the real offline CA and verified by the authority,
* each session's ledger entry is produced by the real ``Authority`` calling the
  real witness processes over HTTP -- the entries in ``sessions.jsonl`` are the
  leaves in ``ledger.db``, not rows written to match them,
* each marked copy is marked by :meth:`ClientNode.mark_copy`, the same code path
  a recipient's client runs,
* each leak artefact is produced from a real marked copy, and the OCR path
  really renders and really OCRs.

What the generator deliberately does not do is invent ground truth it cannot
check. The ``truth`` recorded beside each leak is the *intended* recipient of
that open, taken from the ledger entry's own signed request -- so it is a fact
about the ledger, not a hint written by the harness about what it hopes the
investigator will say. Whether the leak-check pipeline actually recovers it is
what ``--verify`` reports, and it reports the failures too.

Reproducibility
---------------
The corpus is deterministic given ``--seed``. The dataset as a whole is not, and
cannot be: ML-DSA signing is randomised, so two runs produce different
signatures, different leaf hashes, different watermark seeds and therefore
different marked copies. ``manifest.json`` records this rather than leaving a
future reader to discover that `diff -r` of two runs is never empty.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

from ..watermark import linguistic, payload
from . import corpus as corpus_mod
from .scenario import SIMULATED, Scenario

# Every generated dataset carries this, so a downstream consumer cannot be
# surprised by what is and is not real. Kept next to SIMULATED (which the API
# also serves) so the two lists cannot drift apart without a diff.
REAL = (
    "ledger entries: every session in sessions.jsonl is a real leaf in "
    "ledger.db, committed by the real authority after a real witness quorum",
    "signatures: ML-DSA-65 request signatures and witness co-signatures, from "
    "keys issued by the real CA",
    "marked copies: produced by ClientNode.mark_copy, the path a client runs",
    "leak artefacts: rendered and OCR'd for real; the screenshot path really "
    "calls tesseract",
)

DETERMINISM = (
    "the corpus text is deterministic given --seed",
    "the dataset as a whole is not: ML-DSA signing is randomised, so "
    "signatures, leaf hashes, watermark seeds and marked copies differ between "
    "runs even at the same seed. This is a property of the cryptography, not a "
    "bug in the generator; a deterministic signature scheme would be a "
    "catastrophic one",
)


def _write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)


def _append_jsonl(fh, obj) -> None:
    fh.write(json.dumps(obj, sort_keys=True) + "\n")


def _session_row(sc: Scenario, deps: dict, doc: dict, recipient_id: str,
                 out: dict, session: int) -> dict:
    """Turn a real open result into the row that goes in ``sessions.jsonl``.

    One function for every path that commits a session, because the alternative
    is what this generator did first and got wrong: the leak builder wrote its
    own truth from the *planned* session while ``leak_text`` performed a fresh
    open, so the recorded ledger index belonged to a different entry than the
    artefact, and every leak-check "miss" was the harness lying about its own
    data rather than the pipeline failing.

    Everything here is read back from the committed leaf, not from the caller's
    intent. The ``ledger_index`` is the one the authority returned; the
    timestamp and device fingerprint are parsed out of the leaf itself.
    """
    idx = out["ledger_index"]
    leaf = json.loads(sc.log.get_leaf(idx))
    cfg = deps["tardos"]
    slots = linguistic.slot_count(doc["text"])
    plan = payload.plan_for_document(slots, len(cfg["users"]),
                                     cfg["colluders"], cfg["eps"])
    return {
        "session": session, "ok": True,
        "doc_id": doc["doc_id"], "recipient_id": recipient_id,
        "ledger_index": idx, "leaf_hash": out["leaf_hash"],
        "tree_size": out["tree_size"],
        "watermark_seed": out["watermark_seed"],
        "timestamp": leaf["request"]["timestamp"],
        "device_fp": leaf["request"]["device_fp"],
        "source_ip": leaf.get("source_ip"),
        "slots": slots,
        "pointer_bits": plan["pointer_bits"],
        "tardos_bits": plan["tardos_bits"],
        "tardos_required": plan["tardos_required"],
        "guarantee": plan["guarantee"],
        # Whether a mark was actually embedded, which is not the same as whether
        # the call returned text: ``mark_copy`` returns the plaintext unchanged
        # when the document is too short to carry a payload, so testing for a
        # returned string would report an unmarked copy as marked and make an
        # unusable document look like a working session.
        "marked": bool(plan["ok"]),
        "mark_reason": "" if plan["ok"] else plan["reason"],
    }


def _plan_sessions(rng: random.Random, docs: list[dict], recipients: list[str],
                   n: int) -> list[dict]:
    """Which recipient opens which document, ``n`` times.

    Weighted so that every recipient opens several documents and every document
    is opened by several recipients. A random draw would leave some pair
    untouched, and an untouched pair is exactly where a bug in the per-recipient
    marking would hide. The repetition matters too: the same recipient opening
    the same document twice is the case the seed-per-session design exists for,
    and it should appear in the data rather than only in a unit test.
    """
    plan = []
    for i in range(n):
        doc = docs[i % len(docs)]
        rid = recipients[(i * 3 + i // len(docs)) % len(recipients)]
        plan.append({"doc_id": doc["doc_id"], "recipient_id": rid,
                     "mark": True})
    # A couple of deliberate repeats of an already-used pair, so a dataset built
    # with a small --sessions still contains one.
    if plan:
        for k in range(min(2, len(plan))):
            src = plan[k]
            plan.append({"doc_id": src["doc_id"],
                         "recipient_id": src["recipient_id"], "mark": True})
    rng.shuffle(plan)
    return plan


def generate(out_dir: str, *, n_docs: int = 8, target_words: int = 1800,
             seed: int = 7, recipients: list[str] | None = None,
             n_sessions: int = 24, n_leaks: int = 6,
             data_dir: str | None = None, min_witnesses: int = 2,
             witness_ports: list[int] | None = None,
             verbose: bool = True) -> dict:
    """Build a dataset under ``out_dir`` and return its manifest.

    ``data_dir`` is where the deployment lives (keys, ledger, witness state).
    Defaulting it inside ``out_dir`` keeps a generated dataset self-contained,
    which is what makes it re-runnable by someone else -- but note that it then
    also contains the CA and authority private keys, because
    :meth:`Deployment.create` writes them in plaintext. The manifest says so:
    a dataset directory is a *demo* artefact and must not be published as though
    it were inert.
    """
    recipients = recipients or ["alice", "bob", "carol", "dave", "erin",
                                "frank"]
    out_dir = os.path.abspath(out_dir)
    data_dir = data_dir or os.path.join(out_dir, "deployment")
    os.makedirs(out_dir, exist_ok=True)

    started = time.time()
    log = print if verbose else (lambda *a, **k: None)

    # 1. The corpus. Deterministic, and written before anything cryptographic so
    #    that a failure later still leaves a usable corpus on disk.
    docs = corpus_mod.make_document_set(n_docs, seed=seed,
                                        target_words=target_words)
    corpus_dir = os.path.join(out_dir, "corpus")
    os.makedirs(corpus_dir, exist_ok=True)
    corpus_rows = []
    for d in docs:
        path = os.path.join(corpus_dir, f"{d['doc_id']}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(d["text"])
        corpus_rows.append({**{k: v for k, v in d.items() if k != "text"},
                            "path": os.path.relpath(path, out_dir)})
    _write_json(os.path.join(out_dir, "corpus.json"), {
        "documents": corpus_rows,
        "density": corpus_mod.density_report(docs),
        "seed": seed,
        "target_words": target_words})
    log(f"corpus: {len(docs)} documents -> {corpus_dir}")

    # 2. A live deployment with real witnesses.
    log(f"starting {min_witnesses}+ witness processes under {data_dir} ...")
    sc = Scenario.build(data_dir, n_docs=n_docs, target_words=target_words,
                        seed=seed, recipients=recipients,
                        start_witnesses=True, min_witnesses=min_witnesses,
                        fresh=True, witness_ports=witness_ports)
    try:
        return _drive(sc, out_dir, docs, recipients, n_sessions, n_leaks,
                      seed, target_words, started, log)
    finally:
        sc.close()


def _drive(sc: Scenario, out_dir: str, docs: list[dict], recipients: list[str],
           n_sessions: int, n_leaks: int, seed: int, target_words: int,
           started: float, log) -> dict:
    dep = sc.dep

    # 3. Distribute every document to every recipient. Not the interesting part
    #    of the system, but the sessions below are meaningless without it, and
    #    granting to everyone is what makes the leak-check's candidate list
    #    (everyone who *could* have opened it) non-trivial.
    grants = {}
    for d in docs:
        sc.authority.seal(d["text"], d["doc_id"], d["classification"],
                          recipients)
        grants[d["doc_id"]] = sorted(recipients)
    log(f"sealed {len(docs)} documents for {len(recipients)} recipients")

    # 4. Identities, public parts only. The private halves stay in the
    #    deployment directory; a dataset that shipped recipient signing keys
    #    would let anyone forge the very signatures the system rests on.
    identities = []
    for rid in recipients:
        cert = dep.cert_for(rid)
        identities.append({
            "recipient_id": rid, "role": getattr(cert, "role", "recipient"),
            "certificate": dataclasses.asdict(cert),
            "sig_pub": cert.sig_pub, "kem_pub": cert.kem_pub,
            "tardos_user_index": sorted(recipients).index(rid),
        })
    _write_json(os.path.join(out_dir, "identities.json"), {
        "recipients": identities,
        "ca_pub": dep.ca_pub.hex(),
        "log_pub": sc.log.log_pub.hex(),
        "witness_pubs": {k: v.hex() for k, v in dep.witness_pubs().items()},
        "note": "public halves only; private keys remain in the deployment "
                "directory and are not part of this dataset"})

    # 5. Sessions: real opens, real ledger appends, real marks.
    rng = random.Random(seed ^ 0x5EED)
    plan = _plan_sessions(rng, docs, sorted(recipients), n_sessions)
    sessions_path = os.path.join(out_dir, "sessions.jsonl")
    deps = {"tardos": dep.tardos_config()}
    session_rows = []
    with open(sessions_path, "w", encoding="utf-8") as fh:
        for i, step in enumerate(plan):
            doc = sc.doc(step["doc_id"])
            try:
                out = sc.node(step["recipient_id"]).open(doc["doc_id"],
                                                         mark=step["mark"])
            except Exception as e:                      # noqa: BLE001
                # A refused open is data too. It must be recorded as a refusal
                # rather than skipped: silently dropping it would make the
                # dataset look like every open succeeds, which is precisely the
                # claim the fail-closed design refuses to make.
                _append_jsonl(fh, {"session": i, "ok": False,
                                   "doc_id": doc["doc_id"],
                                   "recipient_id": step["recipient_id"],
                                   "error": f"{type(e).__name__}: {e}"})
                log(f"  session {i}: REFUSED {step['recipient_id']} / "
                    f"{step['doc_id']}: {e}")
                continue

            row = _session_row(sc, deps, doc, step["recipient_id"], out, i)
            _append_jsonl(fh, row)
            session_rows.append(row)
            if verbose_every(i):
                log(f"  session {i}: {step['recipient_id']} opened "
                    f"{doc['doc_id']} -> ledger index {row['ledger_index']}")

        # 6. Leak artefacts, from real marked copies. Each one opens again, so
        #    it appends more ledger entries; those are written into the same
        #    sessions file, because a sessions file that does not list every
        #    entry in the ledger is a file that cannot be checked against it.
        leaks_dir = os.path.join(out_dir, "leaks")
        os.makedirs(leaks_dir, exist_ok=True)
        leak_rows = _make_leaks(sc, deps, leaks_dir, session_rows, n_leaks, log,
                                fh, len(plan))

    ok_rows = [r for r in session_rows if r["ok"]]
    log(f"sessions: {len(ok_rows)} committed, "
        f"{len([r for r in session_rows if not r['ok']])} refused, "
        f"{len(session_rows) - len(plan)} from leak generation")

    # 7. Externalize the root before bundling.
    #
    #    Without this the bundle verifies its entries but can say nothing about
    #    the *history*, and the standalone verifier says exactly that -- a
    #    rewritten ledger would go undetected. An anchor is what turns "these
    #    entries are in some tree" into "these entries are in a tree that
    #    extends a root which left this machine". Generating a dataset without
    #    one would produce a demo whose central claim is unchecked, so it is not
    #    optional here even though ``--no-anchors`` exists on the exporter.
    anchor = sc.authority.anchor_now()
    if anchor is not None:
        log(f"anchor: size {anchor.get('tree_size')} root "
            f"{str(anchor.get('root_hash'))[:16]}... externalized")
    else:
        log("anchor: none externalized (no anchorer configured)")

    # 8. An evidence bundle over every session's entry, so a third party can
    #    check the whole dataset with the standalone verifier and no access to
    #    anything in this repository's runtime.
    bundle_path = os.path.join(out_dir, "evidence-bundle.json")
    from ..forensics.bundle import BundleExporter
    from ..ledger.anchor import read_anchors

    exporter = BundleExporter.from_deployment(dep, sc.log)
    indexes = [r["ledger_index"] for r in ok_rows]
    if indexes:
        anchors_path = dep.path("anchors.jsonl")
        anchors = (read_anchors(anchors_path)
                   if os.path.exists(anchors_path) else [])
        exporter.save(sc.log, indexes, bundle_path, anchors)
        log(f"evidence bundle: {len(indexes)} entries -> {bundle_path}")
    else:
        # No session committed, so there is nothing to bundle. Said out loud
        # rather than left as a missing file the reader has to notice.
        bundle_path = None
        log("evidence bundle: skipped, no sessions committed")

    # 9. The raw ledger, so the dataset can be checked against the log it claims
    #    to describe rather than only against the summary written here.
    ledger_path = os.path.join(out_dir, "ledger-export.jsonl")
    with open(ledger_path, "w", encoding="utf-8") as fh:
        for i in range(sc.log.tree_size()):
            leaf = sc.log.get_leaf(i)
            from ..ledger import merkle

            _append_jsonl(fh, {"index": i, "leaf": leaf.decode("utf-8"),
                               "leaf_hash": merkle.leaf_hash(leaf).hex()})
    head = sc.log.latest_sth()

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "parameters": {
            "documents": len(docs), "target_words": target_words,
            "recipients": len(recipients),
            "sessions_requested": len(plan), "sessions_committed": len(ok_rows),
            "leaks": len(leak_rows), "min_witnesses": dep.min_witnesses,
        },
        "counts": {
            "ledger_entries": sc.log.tree_size(),
            "tree_size": sc.log.tree_size(),
            "documents_sealed": len(grants),
            "recipients": len(recipients),
            "witnesses": len(dep.witness_pubs()),
        },
        "head": head.to_dict() if head else None,
        "simulated": list(SIMULATED),
        "real": list(REAL),
        "determinism": list(DETERMINISM),
        "tardos": {k: v for k, v in dep.tardos_config().items() if k != "seed"},
        "files": {
            "corpus": "corpus.json", "identities": "identities.json",
            "sessions": "sessions.jsonl", "leaks": "leaks/",
            "bundle": "evidence-bundle.json" if ok_rows else None,
            "ledger": "ledger-export.jsonl",
        },
        "warning_private_keys": (
            "the deployment directory contains the CA private key and the "
            "authority's KEM private key in plaintext, because that is how this "
            "demo runs; it is not a distributable artefact"),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    _write_json(os.path.join(out_dir, "manifest.json"), manifest)
    log(f"manifest -> {os.path.join(out_dir, 'manifest.json')} "
        f"({manifest['elapsed_seconds']}s)")
    return manifest


def verbose_every(i: int) -> bool:
    """Log every session early on, then thin out. A 500-session run should not
    bury the interesting lines."""
    return i < 5 or i % 10 == 0


def _make_leaks(sc: Scenario, deps: dict, leaks_dir: str, sessions: list[dict],
                n: int, log, sessions_fh, first_session: int) -> list[dict]:
    """Leak artefacts of each kind, with their truth read off the real open.

    ``truth`` comes from the receipt of the open that produced *this* artefact
    -- ``out["ledger_index"]`` returned by ``leak_text``/``leak_screenshot`` --
    and never from the session the plan intended. Those are different numbers:
    each leak build performs a fresh open and therefore commits a fresh ledger
    entry. Taking the planned session's index instead was the first version of
    this function, and it made every "miss" in the verify report a lie about the
    harness rather than a fact about the pipeline.

    The leak's own session rows are appended to ``sessions_fh`` for the same
    reason: the ledger grows during leak generation, and a sessions file that
    does not account for every entry cannot be reconciled against the ledger.
    """
    if not sessions:
        return []
    # Snapshot the pool before appending to ``sessions`` below: the loop indexes
    # into it to choose which session a leak is built from, and growing the list
    # underneath that would silently change which session each later leak came
    # from as the run progressed.
    pool = list(sessions)
    kinds = ["text", "screenshot", "collusion"]
    rows = []
    extra = 0
    for i in range(n):
        kind = kinds[i % len(kinds)]
        s = pool[(i * 5) % len(pool)]
        doc_id, rid = s["doc_id"], s["recipient_id"]
        try:
            doc = sc.doc(doc_id)
            if kind == "text":
                out = sc.leak_text(rid, doc_id)
                opened = [out["opened"]]
                row = {"kind": "text", "doc_id": doc_id, "recipient_id": rid,
                       "truth": {"ledger_index": out["ledger_index"],
                                 "recipient_id": rid}}
            elif kind == "screenshot":
                attack = ["jpeg85", "jpeg50", "resize60", "blur1",
                          "contrast70", "combo"][i % 6]
                out = sc.leak_screenshot(rid, doc_id, attack=attack)
                png = os.path.join(leaks_dir, f"leak-{i:03d}.png")
                out["image"].save(png)
                opened = [out["opened"]]
                row = {"kind": "screenshot", "doc_id": doc_id,
                       "recipient_id": rid, "attack": attack,
                       "image": os.path.relpath(png, leaks_dir),
                       "truth": {"ledger_index": out["ledger_index"],
                                 "recipient_id": rid}}
            else:
                other = next((r["recipient_id"] for r in sessions
                              if r["recipient_id"] != rid), rid)
                out = sc.leak_collusion(rid, other, doc_id, seed=1000 + i)
                opened = list(out["opened"])
                row = {"kind": "collusion", "doc_id": doc_id,
                       "colluders": [rid, other],
                       "positions_differing": out["positions_differing"],
                       "truth": {"ledger_indices": out["ledger_indices"],
                                 "colluders": out["colluders"],
                                 "note": "at least one of these must be "
                                         "ranked; naming both is not required"}}

            for j, o in enumerate(opened):
                who = rid if j == 0 else row.get("colluders", [rid, rid])[1]
                srow = _session_row(sc, deps, doc, who, o, first_session + extra)
                extra += 1
                _append_jsonl(sessions_fh, srow)
                sessions.append(srow)

            # A collusion has two opens behind it and so two indices; a leak of
            # one copy has one. Recorded as a list either way, so a consumer
            # does not have to know which kind of artefact it is looking at to
            # find the ledger entries -- that is exactly the sort of thing a
            # reader gets wrong once and then trusts.
            if kind == "collusion":
                row["ledger_indices"] = list(out["ledger_indices"])
                row["ledger_index"] = out["ledger_indices"][0]
            else:
                row["ledger_index"] = out["ledger_index"]
                row["ledger_indices"] = [out["ledger_index"]]
            row["leaked_text"] = out["leaked_text"]
            row["path"] = os.path.relpath(
                os.path.join(leaks_dir, f"leak-{i:03d}.json"), leaks_dir)
            _write_json(os.path.join(leaks_dir, f"leak-{i:03d}.json"), row)
            rows.append(row)
            if verbose_every(i):
                log(f"  leak {i}: {kind} from {rid} / {doc_id} "
                    f"(ledger index {row['ledger_index']})")
        except Exception as e:                          # noqa: BLE001
            log(f"  leak {i}: could not build ({type(e).__name__}: {e})")
    _write_json(os.path.join(leaks_dir, "index.json"), {"leaks": rows})
    log(f"leaks: {len(rows)} artefacts -> {leaks_dir}")
    return rows


def verify(out_dir: str, *, verbose: bool = True) -> dict:
    """Run the leak-check pipeline over every leak in a generated dataset.

    This is the part that makes the generator worth having. Generating data that
    *looks* right is easy; the question is whether the pipeline recovers the
    truth from it, and this reports the answer per artefact -- including the
    ones it gets wrong, which are the only interesting rows.

    The investigator is rebuilt from the deployment the dataset was generated
    against, because the leak-check needs the ledger and the witnesses' public
    keys. That is a real limitation of checking a dataset on the machine that
    produced it; the evidence bundle beside it is the artefact that a third
    party checks instead, with ``python -m verifier.verify``.
    """
    log = print if verbose else (lambda *a, **k: None)
    out_dir = os.path.abspath(out_dir)
    manifest = json.loads(open(os.path.join(out_dir, "manifest.json"),
                               encoding="utf-8").read())
    deployment = os.path.join(out_dir, "deployment")

    index = json.loads(open(os.path.join(out_dir, "leaks", "index.json"),
                            encoding="utf-8").read())
    leaks = index["leaks"]
    if not leaks:
        return {"checked": 0, "results": []}

    results = []
    with Scenario.build(deployment, n_docs=1, start_witnesses=True,
                        min_witnesses=manifest["parameters"]["min_witnesses"]
                        ) as sc:
        # Scenario.build regenerates a corpus, so the documents the dataset was
        # built from are re-read from disk and passed to the investigator
        # explicitly. Without this the identification stage would be comparing
        # leaks against a different corpus and every result would be
        # "unidentified" -- which would look like a pipeline failure and be a
        # harness bug.
        corpus = json.loads(open(os.path.join(out_dir, "corpus.json"),
                                 encoding="utf-8").read())
        docs = []
        for row in corpus["documents"]:
            with open(os.path.join(out_dir, row["path"]), encoding="utf-8") as f:
                docs.append({"doc_id": row["doc_id"], "text": f.read(),
                             "classification": row.get("classification")})
        inv = sc.investigator(docs=docs)
        for leak in leaks:
            got = inv.investigate(leaked_text=leak["leaked_text"])
            truth = leak["truth"]
            if leak["kind"] == "collusion":
                colluders = set(truth["colluders"])
                ranked = [c.recipient_id for c in got.candidates]
                hit = bool(colluders & set(ranked[:2]))
                expected = "one of " + "/".join(sorted(colluders)) + \
                           " ranked in the top two"
            else:
                hit = (got.pointer_index == truth["ledger_index"]
                       and got.status == "attributed")
                expected = f"attributed to ledger entry {truth['ledger_index']}"
            results.append({
                "leak": leak["path"], "kind": leak["kind"], "hit": hit,
                "status": got.status, "expected": expected,
                "pointer_index": got.pointer_index,
                "candidates": [c.recipient_id for c in got.candidates[:3]],
                "doc_confidence": round(got.doc_confidence, 4),
                "watermark_confidence": round(got.watermark_confidence, 4),
                "notes": got.notes[:2],
            })
            if verbose:
                mark = "ok  " if hit else "MISS"
                # The criterion is printed beside the verdict on purpose. "ok"
                # means different things for the two kinds -- a text leak has to
                # be attributed to the right ledger entry, while a collusion only
                # has to rank one real colluder in the top two -- and a bare "ok"
                # next to `status=no-watermark` reads as "the pipeline got the
                # right answer" when what it actually means is "the right person
                # was ranked, though the pointer did not survive". The status is
                # the pipeline's own verdict and is shown unaltered.
                log(f"  {mark} {leak['kind']:<10} status={got.status:<22} "
                    f"candidates={[c.recipient_id for c in got.candidates[:3]]}"
                    f"  | judged on: {expected}")

    hits = sum(1 for r in results if r["hit"])
    summary = {"checked": len(results), "hits": hits,
               "misses": len(results) - hits, "results": results}
    by_kind: dict[str, list[int]] = {}
    for r in results:
        b = by_kind.setdefault(r["kind"], [0, 0])
        b[0] += 1
        b[1] += 1 if r["hit"] else 0
    summary["by_kind"] = {k: {"n": v[0], "hits": v[1]}
                          for k, v in sorted(by_kind.items())}
    _write_json(os.path.join(out_dir, "verify-report.json"), summary)
    log(f"verify: {hits}/{len(results)} recovered -> "
        f"{os.path.join(out_dir, 'verify-report.json')}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="generate",
        description="Build a synthetic logfirst deployment: corpus, identities, "
                    "open sessions, marked copies and leak artefacts.")
    ap.add_argument("--out", default="dataset", help="output directory")
    ap.add_argument("--docs", type=int, default=8)
    ap.add_argument("--words", type=int, default=1800)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--recipients", default="alice,bob,carol,dave,erin,frank")
    ap.add_argument("--sessions", type=int, default=24)
    ap.add_argument("--leaks", type=int, default=6)
    ap.add_argument("--witnesses", type=int, default=2,
                    help="witness quorum (three processes run regardless; this "
                         "is how many must co-sign before a key is released)")
    ap.add_argument("--data", default=None,
                    help="deployment directory (default: <out>/deployment)")
    ap.add_argument("--verify", action="store_true",
                    help="after generating, run the leak-check pipeline over "
                         "every leak and report how many it recovers")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    recipients = [r.strip() for r in args.recipients.split(",") if r.strip()]
    manifest = generate(args.out, n_docs=args.docs, target_words=args.words,
                        seed=args.seed, recipients=recipients,
                        n_sessions=args.sessions, n_leaks=args.leaks,
                        data_dir=args.data, min_witnesses=args.witnesses,
                        verbose=not args.quiet)

    if args.verify:
        print()
        report = verify(args.out, verbose=not args.quiet)
        if report["misses"]:
            print(f"\n{report['misses']} of {report['checked']} leaks were not "
                  f"recovered; see verify-report.json for the per-artefact "
                  f"detail. A miss is a result, not a crash: report it.",
                  file=sys.stderr)
            return 1
    print(f"\ndataset at {os.path.abspath(args.out)} "
          f"({manifest['counts']['ledger_entries']} ledger entries, "
          f"{manifest['elapsed_seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
