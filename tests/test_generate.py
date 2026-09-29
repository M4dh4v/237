"""The synthetic dataset generator, checked against the ledger it claims to describe.

``generate.py`` is the one component whose output is *data about the system*
rather than part of it, and that makes it the easiest place in the repository
for a lie to survive. A generator can emit a manifest, a sessions file and a set
of leak artefacts that are internally consistent and describe a run that never
happened; every downstream reader would then be reasoning about fiction. Its own
docstring records that this happened once already, in the opposite direction:
the leak builder recorded the *planned* session's ledger index while performing
a fresh open, so the truth it published belonged to a different entry than the
artefact, and every "miss" in the verify report was the harness misdescribing
its own data rather than the pipeline failing.

So nothing here trusts a summary. Every number the manifest reports is
re-derived from the files on disk, and every leak's truth is followed back to a
real ledger entry whose leaf names the recipient the leak came from.

``verify()`` is the end-to-end claim and is exercised last, because it re-runs
the pipeline over the artefacts -- which is the only thing that distinguishes a
dataset that is *shaped* like a leak corpus from one the system can actually
read.
"""

from __future__ import annotations

import json
import os
import socket

import pytest

from logfirst.data import generate as gen

# Small but not degenerate: 1500 words is the first size in the capacity table
# where a document carries both a pointer and a Tardos field, so an "unmarked
# because the document was too short" result cannot be mistaken for a pipeline
# failure. Two documents and two leaks keep the run near ten seconds.
DOCS = 2
WORDS = 1500
SESSIONS = 4
LEAKS = 2
RECIPIENTS = ["alice", "bob", "carol", "dave"]


def _free_ports(n: int) -> list[int]:
    """Bind-and-release, so this run does not fight a live demo for 9101.

    The default witness ports are fixed. Without this, running the suite beside
    ``make demo-serve`` -- or beside another pytest -- fails with a message
    about a stale witness whose state file disagrees with the ledger, which
    describes the wrong problem entirely. ``tests/test_demo_api.py`` draws ports
    for the same reason.
    """
    out = []
    for _ in range(n):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            out.append(s.getsockname()[1])
    return out


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    """One real generate run, shared by every test in this file."""
    out = str(tmp_path_factory.mktemp("dataset"))
    manifest = gen.generate(out, n_docs=DOCS, target_words=WORDS, seed=11,
                            recipients=RECIPIENTS, n_sessions=SESSIONS,
                            n_leaks=LEAKS, min_witnesses=2,
                            witness_ports=_free_ports(3), verbose=False)
    return {"out": out, "manifest": manifest}


def _read(out, *parts):
    with open(os.path.join(out, *parts), encoding="utf-8") as fh:
        return json.load(fh)


def _jsonl(out, name):
    with open(os.path.join(out, name), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ==========================================================================
# The dataset describes the ledger it claims to describe
# ==========================================================================

def test_every_file_the_manifest_promises_is_actually_there(dataset):
    """A manifest is a set of promises. Broken ones must not need a reader to
    notice by hand."""
    out, man = dataset["out"], dataset["manifest"]
    assert man["files"]["corpus"] and os.path.exists(
        os.path.join(out, man["files"]["corpus"]))
    for key in ("corpus", "identities", "sessions", "ledger"):
        assert man["files"][key], f"the manifest promises no {key} file"
        assert os.path.exists(os.path.join(out, man["files"][key])), \
            f"the manifest promises {man['files'][key]}, which is not on disk"
    if man["files"]["bundle"]:
        assert os.path.exists(os.path.join(out, man["files"]["bundle"]))
    assert os.path.isdir(os.path.join(out, "leaks"))


def test_the_manifest_counts_are_recounted_from_the_files(dataset):
    """The numbers in the manifest, re-derived.

    ``counts.ledger_entries`` is the one that matters: it is the size of the
    tree the dataset claims to have produced, and a sessions file plus a ledger
    export that do not add up to it is a dataset nobody can check.
    """
    out, man = dataset["out"], dataset["manifest"]
    ledger = _jsonl(out, man["files"]["ledger"])
    sessions = _jsonl(out, man["files"]["sessions"])
    corpus = _read(out, man["files"]["corpus"])

    assert man["counts"]["ledger_entries"] == len(ledger) == \
        man["counts"]["tree_size"]
    assert man["parameters"]["documents"] == len(corpus["documents"]) == DOCS
    assert man["counts"]["recipients"] == len(RECIPIENTS)
    assert man["counts"]["witnesses"] >= man["parameters"]["min_witnesses"], (
        "a deployment with fewer witnesses than its own quorum would make the "
        "tamper-evidence in this dataset vacuous")

    # The ledger export is a contiguous run from zero -- no gaps, no duplicates.
    assert [row["index"] for row in ledger] == list(range(len(ledger)))


def test_every_session_index_resolves_to_the_leaf_hash_the_session_records(
        dataset):
    """The sessions file and the ledger export must agree leaf for leaf.

    This is the join the whole dataset rests on: a leak-check result names a
    ledger index, and if the sessions file described that index with a different
    leaf hash than the ledger holds, an analyst following the pointer would be
    reading about an entry that does not exist.
    """
    out, man = dataset["out"], dataset["manifest"]
    ledger = {row["index"]: row for row in _jsonl(out, man["files"]["ledger"])}
    rows = [r for r in _jsonl(out, man["files"]["sessions"]) if r.get("ok")]
    assert rows, "no session committed, so this dataset tests nothing"
    for row in rows:
        entry = ledger.get(row["ledger_index"])
        assert entry is not None, (
            f"session {row['session']} names ledger index "
            f"{row['ledger_index']}, which is not in the export")
        assert entry["leaf_hash"] == row["leaf_hash"], (
            f"session {row['session']} and the ledger disagree about index "
            f"{row['ledger_index']}")
        leaf = json.loads(entry["leaf"])
        assert leaf["request"]["recipient_id"] == row["recipient_id"]
        assert leaf["request"]["doc_id"] == row["doc_id"]


def test_the_recorded_device_and_timestamp_come_from_the_leaf(dataset):
    """The row's fields are read out of the committed leaf, not composed.

    A generator could write a plausible device fingerprint into the sessions
    file and one that disagrees with the ledger would be invisible except to
    someone cross-checking by hand.
    """
    out, man = dataset["out"], dataset["manifest"]
    ledger = {row["index"]: row for row in _jsonl(out, man["files"]["ledger"])}
    for row in _jsonl(out, man["files"]["sessions"]):
        if not row.get("ok"):
            continue
        leaf = json.loads(ledger[row["ledger_index"]]["leaf"])
        assert row["timestamp"] == leaf["request"]["timestamp"]
        assert row["device_fp"] == leaf["request"]["device_fp"]


# ==========================================================================
# The dataset is real cryptography, not a written-down summary
# ==========================================================================

def test_the_sessions_carry_witness_cosignatures_that_verify(dataset):
    """Checked against the witnesses' own published keys, from identities.json.

    The point of shipping the dataset is that somebody else can check it. If the
    co-signatures in it did not verify under the keys the dataset publishes, the
    dataset would be self-describing and worthless.
    """
    from logfirst.crypto import pqc
    from logfirst.models import STH

    out, man = dataset["out"], dataset["manifest"]
    ident = _read(out, man["files"]["identities"])
    pubs = ident["witness_pubs"]
    assert pubs, "no witness public keys published"

    head = man["head"]
    assert head is not None, "the dataset records no tree head"
    sth = STH.from_dict(head)
    ok = [wid for wid, pub in pubs.items()
          if sth.witness_sigs.get(wid)
          and pqc.verify(bytes.fromhex(pub), sth.tbs(),
                         bytes.fromhex(sth.witness_sigs[wid]))]
    assert len(ok) >= man["parameters"]["min_witnesses"], (
        f"only {len(ok)} co-signature(s) verify against the published keys; "
        f"the quorum is {man['parameters']['min_witnesses']}")
    assert pqc.verify(bytes.fromhex(ident["log_pub"]), sth.tbs(),
                      bytes.fromhex(sth.log_sig))


def test_identities_publish_public_keys_and_nothing_key_shaped(dataset):
    """The dataset's identity file is the one a reader would treat as shareable.

    The deployment directory *does* hold private keys in plaintext and the
    manifest says so; this file does not, and the check is structural rather
    than a search for the word "private" -- the file's own note contains that
    word, so a substring test would fail on the disclaimer and pass on a leak.
    What is asserted instead is that every field is named like a public thing,
    and that the key material present is exactly the length of the public half
    of the algorithm it claims to be. A private key pasted into a public field
    would be a different length, which is the failure this is here to catch.
    """
    out, man = dataset["out"], dataset["manifest"]
    ident = _read(out, man["files"]["identities"])
    assert ident["note"], "the identity file does not say what it publishes"

    # Sizes in hex characters: ML-DSA-65 public key 1952 bytes, ML-KEM-768
    # public key 1184 bytes. The secret halves are 4032 and 2400 bytes, so a
    # swapped-in private key cannot pass as one of these.
    SIG_PUB_HEX, KEM_PUB_HEX = 1952 * 2, 1184 * 2
    forbidden = ("sec", "secret", "priv", "seed", "sk")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(t in k.lower() for t in forbidden), (
                    f"identities.json has a field named {path}{k!r}, which is "
                    "not something a public identity file should carry")
                walk(v, f"{path}{k}.")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}].")

    walk(ident)

    for row in ident["recipients"]:
        assert len(row["sig_pub"]) == SIG_PUB_HEX, (
            f"{row['recipient_id']}'s sig_pub is {len(row['sig_pub'])} hex "
            f"chars; ML-DSA-65 public keys are {SIG_PUB_HEX}")
        assert len(row["kem_pub"]) == KEM_PUB_HEX, (
            f"{row['recipient_id']}'s kem_pub is {len(row['kem_pub'])} hex "
            f"chars; ML-KEM-768 public keys are {KEM_PUB_HEX}")
        assert row["certificate"]["sig_pub"] == row["sig_pub"]

    for name, pub in ident["witness_pubs"].items():
        assert len(pub) == SIG_PUB_HEX, f"witness {name} publishes {len(pub)}"
    assert len(ident["log_pub"]) == SIG_PUB_HEX

    # And the warning about the deployment directory is stated, not implied.
    assert "plaintext" in man["warning_private_keys"]


# ==========================================================================
# The leak artefacts point at entries that exist and say who made them
# ==========================================================================

def test_every_leak_truth_index_exists_and_names_the_right_recipient(dataset):
    """Follow each leak's truth back to its leaf.

    The generator's published ``truth`` is the answer the pipeline is asked to
    find. If it pointed at an entry belonging to somebody else, a correct
    pipeline would be scored as wrong -- which is exactly the failure the
    module docstring describes from the first version.
    """
    out, man = dataset["out"], dataset["manifest"]
    ledger = {row["index"]: row for row in _jsonl(out, man["files"]["ledger"])}
    index = _read(out, "leaks", "index.json")
    assert index["leaks"], "no leak artefacts were produced"
    for leak in index["leaks"]:
        assert leak["ledger_indices"], f"{leak['path']} names no ledger entry"
        for idx in leak["ledger_indices"]:
            entry = ledger.get(idx)
            assert entry is not None, (
                f"{leak['path']} points at ledger index {idx}, which does not "
                "exist in the export")
            leaf = json.loads(entry["leaf"])
            assert leaf["request"]["doc_id"] == leak["doc_id"]
        if leak["kind"] == "collusion":
            named = set(leak["truth"]["colluders"])
            assert named == set(leak["colluders"])
            assert len(leak["ledger_indices"]) == len(leak["colluders"]), (
                "a splice has one open behind it per colluder; a different "
                "number means the artefact is not the one described")
        else:
            assert leak["truth"]["recipient_id"] == leak["recipient_id"]
            leaf = json.loads(ledger[leak["truth"]["ledger_index"]]["leaf"])
            assert leaf["request"]["recipient_id"] == leak["recipient_id"], (
                f"{leak['path']}'s truth names {leak['recipient_id']} but "
                f"ledger index {leak['truth']['ledger_index']} records "
                f"{leaf['request']['recipient_id']}")


def test_the_leaked_text_differs_from_the_unmarked_original(dataset):
    """A leak the watermark never touched would test nothing.

    ``mark_copy`` returns the document unchanged when it is too short to carry a
    payload, so "the call returned a string" is not evidence that a mark was
    embedded -- and a dataset of unmarked copies would look like a corpus while
    asking the leak-check to identify an artefact that carries no evidence. Each
    leak's text is therefore compared against the corpus original it came from:
    for the undegraded kinds it must differ, and for the OCR'd kind the
    comparison is skipped, because OCR noise means differing is not informative.
    """
    out, man = dataset["out"], dataset["manifest"]
    corpus = _read(out, man["files"]["corpus"])
    originals = {}
    for row in corpus["documents"]:
        with open(os.path.join(out, row["path"]), encoding="utf-8") as fh:
            originals[row["doc_id"]] = fh.read()

    marked = [s for s in _jsonl(out, man["files"]["sessions"])
              if s.get("ok") and s.get("marked")]
    assert marked, (
        "no session embedded a mark, so every leak in this dataset is a "
        "plaintext copy and the leak-check is being asked to identify an "
        "artefact that carries no evidence -- check the document length "
        f"against the capacity table (target_words={WORDS})")

    checked = 0
    for leak in _read(out, "leaks", "index.json")["leaks"]:
        text = leak["leaked_text"]
        assert text.strip(), f"{leak['path']} carries no text"
        if leak["kind"] == "screenshot":
            continue        # OCR noise: differing proves nothing either way
        assert text != originals[leak["doc_id"]], (
            f"{leak['path']} is byte-identical to the unmarked original of "
            f"{leak['doc_id']}, so it carries no mark to recover")
        checked += 1
    assert checked, "every leak was a screenshot; nothing compared to an original"


def test_the_evidence_bundle_verifies_without_this_repository_running(dataset):
    """The dataset's third-party claim, checked the way a third party checks it.

    ``verifier/`` shares no code with the authority, so this is the one
    assertion in the file that does not take the generator's word for anything:
    it re-checks the signatures, the inclusion proofs and the anchor
    consistency from the bundle alone.
    """
    from verifier.verify import verify_bundle

    out, man = dataset["out"], dataset["manifest"]
    if not man["files"]["bundle"]:
        pytest.skip("no sessions committed, so no bundle was written")
    bundle = _read(out, man["files"]["bundle"])
    report = verify_bundle(bundle)
    assert report["entries_ok"], (
        f"{report['summary']['verified']}/{report['summary']['entries']} "
        f"entries verified; bad witnesses {report['head']['witnesses_bad']}")
    assert report["anchors_present"], (
        "the dataset was generated without an externalized root, so nothing in "
        "it can be checked against a root that left the machine")
    assert report["ok"] is True, report


# ==========================================================================
# The end-to-end claim: the pipeline recovers the published truth
# ==========================================================================

def test_verify_recovers_the_truth_from_the_artefacts(dataset):
    """The generator's whole reason for existing, run for real.

    Generating data that looks like a leak corpus is easy. This is the check
    that the corpus is one the system can read -- and it reports the misses as
    well as the hits, so a regression shows up as a number rather than as a
    silence.
    """
    out = dataset["out"]
    report = gen.verify(out, verbose=False)
    assert report["checked"] == LEAKS, (
        f"verify checked {report['checked']} artefacts, not the {LEAKS} that "
        "were generated")
    assert report["misses"] == 0, (
        "the pipeline did not recover the truth the generator published:\n" +
        "\n".join(f"  {r['leak']}: status={r['status']} "
                  f"candidates={r['candidates']} expected {r['expected']}\n"
                  f"    notes: {r['notes']}"
                  for r in report["results"] if not r["hit"]))
    # And the report is on disk, not only in the return value.
    written = _read(out, "verify-report.json")
    assert written["hits"] == report["hits"]
