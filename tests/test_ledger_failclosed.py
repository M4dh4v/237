"""Fail-closed: no key material without a committed, witnessed entry.

This is the property the entire system is built around, and it is the one where
a plausible-looking implementation is most likely to be quietly wrong. "Append,
then get signatures, then repair if it did not work out" reads as equivalent and
is not: it leaves a window in which a leaf is committed with no valid STH, and a
committed-but-unwitnessed leaf is exactly what the design exists to make
impossible. So the tests here do not merely assert that a failed quorum raises.
They assert that *nothing observable changed*:

* the tree did not grow,
* no row was written to ``leaves`` -- checked by reading the database file
  directly, not the object's in-memory cache, because a cache that was never
  updated and a database that was never written are different claims and only
  the second one matters,
* no row was written to ``sth``, so there is no head at the size the entry would
  have occupied -- which is what makes "there is no witnessed head, therefore no
  key" checkable by a third party rather than merely asserted by the server,
* and the log still works afterwards, because a fail-closed path that corrupts
  the ledger is not fail-closed, it is just a different failure.

The positive direction is tested the same way: the watermark seed returned on
success is recomputed here from the bytes actually stored in the ledger. That
recomputation is the load-bearing assertion, because a seed that is a function
of the committed leaf cannot have existed before the commit. If it were derived
from something the server knew in advance, this test would fail.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from logfirst.crypto import pqc
from logfirst.crypto.kdf import watermark_seed
from logfirst.ledger import merkle
from logfirst.ledger.log import LedgerLog, STHNotWitnessed
from logfirst.ledger.witnesses import (
    QuorumNotMet, WitnessQuorum, WitnessUnavailable,
)
from logfirst.models import STH

from tests.conftest import DeadWitness, InProcessWitness, make_request, make_witnesses


# --------------------------------------------------------------------------
# A witness that misbehaves in a way the quorum does not expect
# --------------------------------------------------------------------------

class ExplodingWitness:
    """Reachable, answers ``max_size``, then raises a non-witness exception.

    The quorum catches ``WitnessUnavailable`` and records a refusal. An
    unexpected exception class is not caught there, so it propagates out of
    ``collect`` and lands in the ledger's bare ``except Exception`` handler.
    That path has its own rollback, and it is the one that would be missed by
    tests that only ever exercise a clean refusal.
    """

    def __init__(self, witness_id: str = "boom"):
        self.witness_id = witness_id

    def info(self):
        return {"witness_id": self.witness_id, "pub": "00"}

    def max_size(self) -> int:
        return 0

    def cosign(self, *a, **kw):
        raise RuntimeError("witness exploded mid-transaction")


def _rows(path, table) -> list[tuple]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        conn.close()


def _open_ledger(tmp_path, witnesses, min_witnesses=2, name="ledger.db"):
    return (LedgerLog.open(str(tmp_path / name),
                           WitnessQuorum(list(witnesses),
                                         min_witnesses=min_witnesses)),
            str(tmp_path / name))


def _one_open(log, rid="alice", doc="DOC-0000"):
    sec = pqc.sig_keypair(pqc.SIG)[1]
    return log.gated_append_for_decryption(
        make_request(rid, doc, sig_sec=sec).leaf_bytes(), "203.0.113.7")


# --------------------------------------------------------------------------
# The positive direction
# --------------------------------------------------------------------------

def test_a_successful_open_commits_and_publishes_a_witnessed_head(tmp_path):
    witnesses = make_witnesses(tmp_path, 3)
    log, path = _open_ledger(tmp_path, witnesses)

    res = _one_open(log)

    assert res["index"] == 0
    assert log.tree_size() == 1
    sth = res["sth"]
    assert sth.tree_size == 1
    assert len(sth.witness_sigs) >= 2
    assert sth.log_sig

    # Every co-signature must verify over the published head's signed body.
    # This is the property that makes a witness signature worth anything: it is
    # over the same bytes the log signed, so a third party holding the STH can
    # check it without asking the witness anything.
    for w in witnesses:
        sig = sth.witness_sigs.get(w.witness_id)
        if sig:
            assert pqc.verify(w.signer.sig_pub, sth.tbs(), bytes.fromhex(sig))

    # And the log's own signature, likewise.
    assert pqc.verify(log.log_pub, sth.tbs(), bytes.fromhex(sth.log_sig))


def test_the_watermark_seed_is_a_function_of_the_committed_leaf(tmp_path):
    """Recompute the seed from the ledger's own bytes.

    This is what makes the seed unusable as an *a priori* value: it is a hash of
    the entry, and the entry contains a fresh nonce and the client's ephemeral
    KEM key, so the server could not have computed it before the append. If the
    seed were derived from a counter or a document id, this recomputation would
    still pass -- so the test also asserts that two opens of the *same document
    by the same recipient* differ.
    """
    witnesses = make_witnesses(tmp_path, 3)
    log, _ = _open_ledger(tmp_path, witnesses)

    res = _one_open(log)
    committed = log.get_leaf(res["index"])
    lh = merkle.leaf_hash(committed)

    assert res["leaf_hash"] == lh.hex()
    assert res["watermark_seed"] == watermark_seed(lh).hex()

    # The inclusion proof in the result folds to the head that was published.
    assert merkle.verify_inclusion(
        committed, res["index"], res["sth"].tree_size,
        [bytes.fromhex(p) for p in res["inclusion_proof"]],
        bytes.fromhex(res["sth"].root_hash))

    second = _one_open(log, rid="alice", doc="DOC-0000")
    assert second["watermark_seed"] != res["watermark_seed"]
    assert second["index"] == 1


def test_the_committed_leaf_carries_the_request_and_the_source(tmp_path):
    """The ledger entry is the signed request plus where it came from."""
    witnesses = make_witnesses(tmp_path, 3)
    log, _ = _open_ledger(tmp_path, witnesses)
    res = _one_open(log, rid="carol", doc="DOC-0009")

    wrapper = json.loads(log.get_leaf(res["index"]).decode())
    assert wrapper["kind"] == "decryption-request"
    assert wrapper["source_ip"] == "203.0.113.7"
    assert wrapper["request"]["recipient_id"] == "carol"
    assert wrapper["request"]["doc_id"] == "DOC-0009"
    assert wrapper["request"]["sig"]


# --------------------------------------------------------------------------
# Quorum failure must change nothing at all
# --------------------------------------------------------------------------

def test_no_witnesses_means_no_leaf_and_no_head(tmp_path):
    dead = [DeadWitness(f"w{i}") for i in (1, 2, 3)]
    log, path = _open_ledger(tmp_path, dead)

    with pytest.raises(STHNotWitnessed) as ei:
        _one_open(log)

    # The exception must say what did not happen, since the caller's next move
    # is to *not* release a key.
    assert "no leaf committed" in str(ei.value)

    assert log.tree_size() == 0
    with pytest.raises(IndexError):
        log.get_leaf(0)
    assert log.latest_sth() is None
    assert log.sth_at(0) is None
    assert log.sth_at(1) is None

    # The database itself, not the object's cache: no leaf, no head.
    assert _rows(path, "leaves") == []
    assert _rows(path, "sth") == []


def test_a_failed_quorum_writes_no_leaf_row_even_though_the_cache_agrees(tmp_path):
    """Read the file directly.

    ``tree_size()`` reads the in-memory cache, which the append never updated on
    the failure path -- so it would report 0 even if the transaction had in fact
    committed. Opening the database fresh is what distinguishes "rolled back"
    from "the object forgot".
    """
    witnesses = make_witnesses(tmp_path, 3)
    log, path = _open_ledger(tmp_path, witnesses)
    _one_open(log)                                  # one good entry
    assert len(_rows(path, "leaves")) == 1

    quorum = WitnessQuorum([DeadWitness("d1"), DeadWitness("d2")], 2)
    log.quorum = quorum
    with pytest.raises(STHNotWitnessed):
        _one_open(log, rid="bob")

    rows = _rows(path, "leaves")
    assert len(rows) == 1, f"a leaf was committed despite the quorum failing: {rows}"
    assert _rows(path, "sth")[-1][0] == 1           # last head is still size 1


def test_one_witness_short_of_the_quorum_is_still_a_failure(tmp_path):
    """The bar is the configured quorum, not "as many as answered"."""
    witnesses = make_witnesses(tmp_path, 3)
    log, path = _open_ledger(tmp_path, witnesses)
    log.quorum = WitnessQuorum(
        [witnesses[0], DeadWitness("w2"), DeadWitness("w3")], min_witnesses=2)

    with pytest.raises(STHNotWitnessed) as ei:
        _one_open(log)

    assert "1/2" in str(ei.value)
    assert log.tree_size() == 0
    assert _rows(path, "leaves") == []


def test_exactly_the_quorum_is_enough(tmp_path):
    """Two of three witnesses up, quorum two: this must succeed.

    The mirror of the test above. Without it, an implementation that failed
    whenever *any* witness was down would pass every negative test here while
    making the system refuse to work in normal operation.
    """
    witnesses = make_witnesses(tmp_path, 3)
    log, _ = _open_ledger(tmp_path, witnesses)
    log.quorum = WitnessQuorum(
        [witnesses[0], witnesses[1], DeadWitness("w3")], min_witnesses=2)

    res = _one_open(log)
    assert log.tree_size() == 1
    assert len(res["sth"].witness_sigs) == 2
    assert len(res["witness_refusals"]) == 1
    assert res["witness_refusals"][0]["witness_id"] == "w3"


def test_an_unexpected_witness_error_also_rolls_back(tmp_path):
    """A crash is not a refusal, and must not be treated as one either.

    ``RuntimeError`` is not caught by the quorum's ``except WitnessUnavailable``,
    so it arrives at the ledger's generic handler. That handler rolls back and
    re-raises -- it must not swallow the exception into a partial commit, and it
    must not leave the transaction open.
    """
    witnesses = make_witnesses(tmp_path, 2)
    log, path = _open_ledger(tmp_path, witnesses)
    log.quorum = WitnessQuorum(
        [witnesses[0], ExplodingWitness("boom")], min_witnesses=2)

    with pytest.raises(RuntimeError, match="exploded"):
        _one_open(log)

    assert _rows(path, "leaves") == []
    assert _rows(path, "sth") == []
    assert log.tree_size() == 0


def test_a_witness_refusal_counts_against_the_quorum(tmp_path):
    """An equivocating witness is a missing co-signature, not a crash.

    A witness that refuses because it has already signed a different root at
    this size raises ``CosignRefused``, which the client maps to
    ``WitnessUnavailable``. The refusal must reduce the available quorum. If it
    were instead treated as a fatal error the log would stop appending on any
    witness disagreement, which is not the design: agreement is enforced by the
    quorum, and disagreement shows up as an inability to reach it.
    """
    witnesses = make_witnesses(tmp_path, 3)
    log, _ = _open_ledger(tmp_path, witnesses)
    _one_open(log)                                   # let them all reach size 1

    # Poison one witness: it has "already signed" a different root at size 2.
    victim = witnesses[2].signer
    victim.signed[2] = {"root_hash": "00" * 32, "sig": "00", "timestamp": "x"}

    log.quorum = WitnessQuorum(
        [witnesses[0], witnesses[1], witnesses[2]], min_witnesses=2)
    res = _one_open(log, rid="bob")

    assert res["index"] == 1
    assert victim.witness_id not in res["sth"].witness_sigs
    assert any(r["witness_id"] == victim.witness_id
               for r in res["witness_refusals"])

    # ...and with the quorum raised to 3, that same refusal is fatal.
    log.quorum = WitnessQuorum(
        [witnesses[0], witnesses[1], witnesses[2]], min_witnesses=3)
    with pytest.raises(STHNotWitnessed):
        _one_open(log, rid="carol")


# --------------------------------------------------------------------------
# Fail-closed means recoverable, not wedged
# --------------------------------------------------------------------------

def test_a_failed_append_leaves_the_log_usable(tmp_path):
    """After a refusal the next append must succeed at index 0.

    If the rollback left the transaction open, or left the cached hash list
    ahead of the database, the recovery append would either fail or produce an
    entry whose proof does not check. Both are worse than the original failure:
    the log would be permanently unable to record the request that was refused.
    """
    witnesses = make_witnesses(tmp_path, 3)
    log, path = _open_ledger(tmp_path, witnesses)

    log.quorum = WitnessQuorum([DeadWitness("x"), DeadWitness("y")], 2)
    with pytest.raises(STHNotWitnessed):
        _one_open(log, rid="alice")

    log.quorum = WitnessQuorum(list(witnesses), min_witnesses=2)
    res = _one_open(log, rid="alice")

    assert res["index"] == 0
    assert log.tree_size() == 1

    # The recovered entry's proof folds to the head that was actually published,
    # so the log is internally coherent rather than merely non-empty.
    committed = log.get_leaf(0)
    assert merkle.verify_inclusion(
        committed, 0, res["sth"].tree_size,
        [bytes.fromhex(p) for p in res["inclusion_proof"]],
        bytes.fromhex(res["sth"].root_hash))
    assert len(_rows(path, "leaves")) == 1


def test_the_ledger_survives_a_restart_intact(tmp_path):
    """Reopening must reproduce the same hashes, or every proof is void."""
    witnesses = make_witnesses(tmp_path, 3)
    log, path = _open_ledger(tmp_path, witnesses)
    before = [_one_open(log, rid=f"u{i}", doc=f"DOC-{i:04d}") for i in range(3)]
    hashes = log.leaf_hashes()
    root = log.current_root()

    reopened = LedgerLog.open(path, WitnessQuorum(list(witnesses), 2))
    assert reopened.leaf_hashes() == hashes
    assert reopened.current_root() == root
    assert reopened.log_pub == log.log_pub
    for b in before:
        assert reopened.get_leaf(b["index"]) == log.get_leaf(b["index"])
        sth = reopened.sth_at(b["index"] + 1)
        assert sth is not None and sth.root_hash == b["sth"].root_hash


# --------------------------------------------------------------------------
# Configuration that would be silently unsatisfiable
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n_witnesses,minimum", [(3, 4), (0, 1), (1, 2), (3, 0)])
def test_an_unsatisfiable_quorum_is_refused_at_construction(n_witnesses, minimum):
    """Refuse at startup, not at the first release.

    A quorum that can never be met is a configuration error that would otherwise
    surface as a mysterious failure to open a document -- with the document
    already encrypted and no way back. The constructor is the cheap place to
    catch it.
    """
    with pytest.raises(ValueError):
        WitnessQuorum([DeadWitness(f"w{i}") for i in range(n_witnesses)],
                      min_witnesses=minimum)


def test_a_witness_that_is_down_does_not_lower_the_bar(tmp_path):
    """The reduction is in available witnesses, never in the threshold."""
    witnesses = make_witnesses(tmp_path, 4)
    q = WitnessQuorum([witnesses[0], DeadWitness("w2"),
                        DeadWitness("w3"), DeadWitness("w4")],
                      min_witnesses=3)
    with pytest.raises(QuorumNotMet) as ei:
        q.collect(1, "aa" * 32, "2026-01-01T00:00:00+00:00", [b"\x00" * 32])
    assert "1/3" in str(ei.value)
