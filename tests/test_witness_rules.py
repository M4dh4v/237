"""What a witness refuses to sign, and that a refusal changes nothing.

A witness that signs whatever it is handed adds nothing: its signature would
then be indistinguishable from the log's own, and the operator running the log
could produce as many as it liked. All of the value is in the refusals, so each
of the three rules gets both directions tested -- the refusal itself, and the
legitimate case that must *not* be refused. A witness that refuses everything
passes every negative test here while making the log unable to append.

The rules:

1. same size + same root  -> idempotent re-sign (a retry after a dropped
   response must not look like an attack)
   same size + other root -> equivocation, refuse
2. smaller size           -> rollback, refuse
3. larger size            -> require a consistency proof from *my own* last root

Two properties are checked that are easy to leave out and that matter more than
the rules themselves:

* **A refusal is not a state change.** After refusing, the witness's history and
  ``max_size`` are exactly what they were. A refusal that partially recorded the
  offered head would let a server walk a witness into a fork by being refused.
* **The history survives a restart.** Rules 1 and 2 are enforced against stored
  state, so a witness that forgot its history on restart could be equivocated
  against trivially: sign root A, restart, sign root B at the same size.
"""

from __future__ import annotations

import pytest

from logfirst.crypto import pqc
from logfirst.ledger import merkle
from logfirst.models import STH
from logfirst.witness.signer import CosignRefused, WitnessSigner

TS = "2026-01-01T00:00:00+00:00"
TS2 = "2026-01-02T00:00:00+00:00"


def leaves(n: int) -> list[bytes]:
    return [merkle.leaf_hash(f"entry-{i}".encode()) for i in range(n)]


def root_of(hashes: list[bytes]) -> str:
    return merkle.root_from_hashes(hashes).hex()


def proof(hashes: list[bytes], m: int, n: int) -> list[str]:
    if m == n:
        return []
    return [p.hex() for p in merkle.consistency_proof(hashes[:n], m, n)]


@pytest.fixture
def witness(tmp_path) -> WitnessSigner:
    return WitnessSigner.open("w1", str(tmp_path / "w1.json"))


# --------------------------------------------------------------------------
# Rule 1: equivocation, and the retry that must not look like one
# --------------------------------------------------------------------------

def test_the_first_signature_needs_no_proof(witness):
    """An empty history has nothing to extend, so rule 3 does not apply."""
    h = leaves(1)
    res = witness.cosign(1, root_of(h), TS, [])
    assert res["already_signed"] is False
    assert res["witness_id"] == "w1"
    assert witness.max_size == 1


def test_signing_the_same_head_twice_is_idempotent(witness):
    """A dropped response and a retry must produce the same signature.

    If a retry were refused as equivocation, a single lost packet would
    permanently wedge the log: the witness would have recorded the head, so
    every subsequent attempt at that size would be a "contradiction".
    """
    h = leaves(3)
    r = root_of(h)
    first = witness.cosign(3, r, TS, [])
    second = witness.cosign(3, r, TS, [])

    assert second["already_signed"] is True
    assert second["sig"] == first["sig"]
    assert len(witness.signed) == 1


def test_a_second_root_at_the_same_size_is_refused(witness):
    """The central attack: a split view.

    To show one history to one witness and another to a second, the operator has
    to get two roots signed at the same size. This is the rule that stops it,
    and the message says EQUIVOCATION so the refusal is legible in a log rather
    than looking like a generic failure.
    """
    a = leaves(3)
    b = leaves(3)
    b[1] = merkle.leaf_hash(b"entry-1-rewritten")
    witness.cosign(3, root_of(a), TS, [])

    with pytest.raises(CosignRefused, match="EQUIVOCATION"):
        witness.cosign(3, root_of(b), TS, [])

    assert witness.signed[3]["root_hash"] == root_of(a)


def test_equivocation_is_still_refused_after_a_restart(tmp_path):
    """Rules 1 and 2 rest on stored state, so the state has to persist.

    A witness that regenerated its history on restart could be equivocated
    against by the trivial expedient of restarting it. This is why the state
    file exists at all, and why losing it is not a recoverable condition.
    """
    path = str(tmp_path / "w1.json")
    w = WitnessSigner.open("w1", path)
    a, b = leaves(3), leaves(3)
    b[0] = merkle.leaf_hash(b"entry-0-rewritten")
    w.cosign(3, root_of(a), TS, [])
    pub = w.sig_pub

    w2 = WitnessSigner.open("w1", path)
    assert w2.sig_pub == pub, "the witness changed identity across a restart"
    assert w2.max_size == 3
    with pytest.raises(CosignRefused, match="EQUIVOCATION"):
        w2.cosign(3, root_of(b), TS, [])
    # And it will still re-sign the head it did sign, so the log recovers.
    assert w2.cosign(3, root_of(a), TS, [])["already_signed"] is True


# --------------------------------------------------------------------------
# Rule 2: no shrinking
# --------------------------------------------------------------------------

def test_a_smaller_size_is_refused_as_a_rollback(witness):
    h = leaves(4)
    witness.cosign(4, root_of(h), TS, [])
    with pytest.raises(CosignRefused, match="ROLLBACK"):
        witness.cosign(3, root_of(h[:3]), TS2, proof(h, 3, 3))


def test_a_rollback_is_refused_even_with_a_valid_proof(witness):
    """Rule 2 does not consult the proof.

    A proof from size 2 to size 3 is a perfectly honest proof. Accepting it
    would mean the log could present a shorter tree -- hiding entries that were
    already committed and attested to -- as a legitimate state, so the size
    check has to come first and stand on its own.
    """
    h = leaves(5)
    witness.cosign(5, root_of(h), TS, [])
    with pytest.raises(CosignRefused, match="ROLLBACK"):
        witness.cosign(2, root_of(h[:2]), TS2, proof(h, 2, 5))
    assert witness.max_size == 5


def test_a_refusal_leaves_the_witness_untouched(witness):
    """Refusing must not record anything.

    If a refused head were partially recorded, a server could walk a witness
    into accepting a fork by first presenting heads it would refuse.

    Each offered head has to be genuinely different from the one already signed,
    or the "equivocation" case is just a re-sign and proves nothing.
    """
    h = leaves(4)
    witness.cosign(4, root_of(h), TS, [])
    before = dict(witness.signed)

    forked = leaves(4)
    forked[3] = merkle.leaf_hash(b"entry-3-rewritten")
    other = leaves(5)
    other[0] = merkle.leaf_hash(b"entry-0-rewritten")

    for args in ((4, root_of(forked), TS),        # equivocation
                 (2, root_of(h[:2]), TS),         # rollback
                 (5, root_of(other), TS)):        # extension with no proof
        with pytest.raises(CosignRefused):
            witness.cosign(*args, [])

    assert witness.signed == before
    assert witness.max_size == 4


# --------------------------------------------------------------------------
# Rule 3: prove the extension
# --------------------------------------------------------------------------

def test_an_extension_without_a_proof_is_refused(witness):
    h = leaves(2)
    witness.cosign(2, root_of(h), TS, [])
    with pytest.raises(CosignRefused, match="NO PROOF"):
        witness.cosign(3, root_of(leaves(3)), TS2, [])


def test_an_extension_that_is_not_a_real_extension_is_refused(witness):
    """The attack rule 3 exists for.

    The offered tree is larger and internally consistent, but it is not the tree
    the witness already signed grown by one. Without this check the witness
    would attest only "some tree of size 3 existed", which the operator could
    satisfy with any history it liked.
    """
    h = leaves(2)
    witness.cosign(2, root_of(h), TS, [])

    other = leaves(3)
    other[0] = merkle.leaf_hash(b"entry-0-rewritten")
    with pytest.raises(CosignRefused, match="BAD PROOF"):
        witness.cosign(3, root_of(other), TS2, proof(other, 2, 3))


def test_an_extension_with_a_proof_from_the_wrong_size_is_refused(witness):
    """A proof of the right shape but the wrong claim does not pass."""
    h = leaves(4)
    witness.cosign(2, root_of(h[:2]), TS, [])
    with pytest.raises(CosignRefused, match="BAD PROOF"):
        witness.cosign(4, root_of(h), TS2, proof(h, 1, 4))


def test_a_genuine_extension_is_signed(witness):
    """The positive direction: the honest path must not be blocked."""
    h = leaves(5)
    witness.cosign(2, root_of(h[:2]), TS, [])
    res = witness.cosign(5, root_of(h), TS2, proof(h, 2, 5))

    assert res["already_signed"] is False
    assert witness.max_size == 5
    assert witness.signed[5]["root_hash"] == root_of(h)


def test_an_extension_can_skip_sizes(witness):
    """Witnesses fall behind independently; catching up in one step is normal."""
    h = leaves(9)
    witness.cosign(1, root_of(h[:1]), TS, [])
    res = witness.cosign(9, root_of(h), TS2, proof(h, 1, 9))
    assert res["tree_size"] == 9
    assert witness.max_size == 9


# --------------------------------------------------------------------------
# What the signature is over
# --------------------------------------------------------------------------

def test_the_signature_is_over_the_logs_timestamp_not_the_witnesss(witness):
    """A witness must co-sign the *same bytes* the log signed.

    If the witness stamped its own clock, its signature would be over a message
    nobody else can reconstruct, so no third party could ever check it against
    the published head. The co-signature would still look present in the STH --
    the failure would be silent until someone tried to verify it. Passing the
    log's timestamp through is what avoids that, so this asserts the property
    directly by checking against an STH built from that timestamp.
    """
    h = leaves(2)
    res = witness.cosign(2, root_of(h), TS, [])
    sth = STH(tree_size=2, root_hash=root_of(h), timestamp=TS)
    assert pqc.verify(witness.sig_pub, sth.tbs(), bytes.fromhex(res["sig"]))
    assert witness.verify_signature(STH(
        tree_size=2, root_hash=root_of(h), timestamp=TS,
        witness_sigs={"w1": res["sig"]}))

    # A head with a different timestamp is a different message.
    wrong = STH(tree_size=2, root_hash=root_of(h), timestamp=TS2,
                witness_sigs={"w1": res["sig"]})
    assert witness.verify_signature(wrong) is False


def test_resigning_the_same_root_under_a_new_timestamp_returns_the_old_signature(
        witness):
    """A sharp edge, pinned so it is a known behaviour rather than a surprise.

    Idempotency is keyed on ``(tree_size, root_hash)``, so asking again for the
    same pair returns the signature issued the first time -- which is bound to
    the *original* timestamp. Checking it against a differently-timestamped head
    fails, and that is the safe direction: the head simply appears unwitnessed
    and no key is released. It cannot be exploited into a forgery, because the
    witness never signs a message it did not sign.

    In practice the log publishes each size exactly once (``sth`` is keyed by
    ``tree_size``), so this does not arise from normal operation.
    """
    h = leaves(2)
    first = witness.cosign(2, root_of(h), TS, [])
    again = witness.cosign(2, root_of(h), TS2, [])
    assert again["already_signed"] is True
    assert again["sig"] == first["sig"]

    sth = STH(tree_size=2, root_hash=root_of(h), timestamp=TS2,
              witness_sigs={"w1": again["sig"]})
    assert witness.verify_signature(sth) is False


def test_a_forged_co_signature_does_not_verify_against_another_witness(tmp_path):
    """Two witnesses are distinct identities, not one key written twice."""
    a = WitnessSigner.open("w1", str(tmp_path / "w1.json"))
    b = WitnessSigner.open("w2", str(tmp_path / "w2.json"))
    assert a.sig_pub != b.sig_pub

    h = leaves(1)
    res = a.cosign(1, root_of(h), TS, [])
    sth = STH(tree_size=1, root_hash=root_of(h), timestamp=TS,
              witness_sigs={"w2": res["sig"]})
    assert b.verify_signature(sth) is False


def test_history_reports_what_was_signed(witness):
    h = leaves(3)
    witness.cosign(1, root_of(h[:1]), TS, [])
    witness.cosign(3, root_of(h), TS2, proof(h, 1, 3))

    hist = witness.history()
    assert hist["witness_id"] == "w1"
    assert hist["max_size"] == 3
    assert hist["signed"] == {"1": root_of(h[:1]), "3": root_of(h)}
