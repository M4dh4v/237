"""The independent verifier's Merkle math, against the server's.

``verifier/core.py`` re-implements the tree hashing and proof folding on purpose,
so that a bug in the server's implementation cannot make a tampered ledger
verify. That only pays off if the two are checked against each other over a wide
input space -- a verifier that is subtly stricter or looser than the server is a
bug in one of them, and both directions matter:

* if the verifier is *looser*, forged proofs are accepted and the tool is worse
  than useless, because it launders a bad bundle into an authoritative-looking
  "VERIFIED";
* if the verifier is *stricter*, honest bundles fail and the tool gets switched
  off.

So this file asserts agreement over the full matrix of sizes, and then asserts
the negative direction explicitly: forgeries and forked histories must be
rejected, and a forked history must be caught rather than merely "not proven".
"""

from __future__ import annotations

import pytest

import verifier.core as vc
from logfirst.ledger import merkle

MAX_N = 64


def data(n: int) -> list[bytes]:
    return [f"leaf-{i}".encode() for i in range(n)]


# --------------------------------------------------------------------------
# The two implementations must agree
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n", range(1, MAX_N + 1))
def test_roots_agree(n):
    d = data(n)
    assert vc.merkle_root(d) == merkle.merkle_root(d)


def test_empty_root_agrees():
    assert vc.merkle_root([]) == merkle.merkle_root([])


def test_inclusion_agrees_over_the_whole_matrix():
    """Every (size, index) pair up to MAX_N: same accept/reject, both ways."""
    checked = 0
    for n in range(1, MAX_N + 1):
        d = data(n)
        hashes = [merkle.leaf_hash(x) for x in d]
        root = merkle.root_from_hashes(hashes)
        vroot = vc.root_from_hashes([vc.leaf_hash(x) for x in d])
        assert root == vroot
        for m in range(n):
            proof = merkle.inclusion_proof(hashes, m)
            theirs = merkle.verify_inclusion(d[m], m, n, proof, root)
            ours = vc.verify_inclusion(d[m], m, n, proof, root)
            assert theirs and ours, f"m={m} n={n}: server={theirs} verifier={ours}"
            checked += 1
    assert checked == MAX_N * (MAX_N + 1) // 2


def test_inclusion_rejects_a_corrupted_proof_in_both():
    d = data(20)
    hashes = [merkle.leaf_hash(x) for x in d]
    root = merkle.root_from_hashes(hashes)
    for m in (0, 1, 7, 13, 19):
        proof = merkle.inclusion_proof(hashes, m)
        for i in range(len(proof)):
            bad = list(proof)
            bad[i] = b"\x00" * 32
            assert not merkle.verify_inclusion(d[m], m, 20, bad, root)
            assert not vc.verify_inclusion(d[m], m, 20, bad, root)


def test_consistency_agrees_over_the_whole_matrix():
    """The matrix that caught a real disagreement when this was first written.

    An earlier version of ``vc.verify_consistency`` folded the two accumulators
    incorrectly and disagreed with the server on 2016 of 2145 cases. Agreement
    here is the regression test for that.
    """
    checked = 0
    for n in range(1, MAX_N + 1):
        d = data(n)
        hashes = [merkle.leaf_hash(x) for x in d]
        for m in range(1, n + 1):
            old_root = merkle.root_from_hashes(hashes[:m])
            new_root = merkle.root_from_hashes(hashes)
            proof = ([] if m == n
                     else merkle.consistency_proof(hashes, m, n))
            theirs = merkle.verify_consistency(m, n, old_root, new_root, proof)
            ours = vc.verify_consistency(m, n, old_root, new_root, proof)
            assert theirs == ours, (
                f"m={m} n={n}: server={theirs} verifier={ours}")
            assert theirs, f"m={m} n={n} should be a valid consistency proof"
            checked += 1
    assert checked == MAX_N * (MAX_N + 1) // 2


# --------------------------------------------------------------------------
# The negative direction: no forgery may be accepted
# --------------------------------------------------------------------------

def test_no_truncated_or_padded_consistency_proof_is_accepted():
    """Neither implementation accepts a truncated or padded proof."""
    d = data(24)
    hashes = [merkle.leaf_hash(x) for x in d]
    cases = 0
    for m in (1, 2, 3, 8, 15, 16, 23):
        old_root = merkle.root_from_hashes(hashes[:m])
        new_root = merkle.root_from_hashes(hashes)
        proof = merkle.consistency_proof(hashes, m, 24)
        candidates = [proof[:k] for k in range(len(proof))]
        candidates += [proof + [b"\x11" * 32] * k for k in (1, 2, 3)]
        candidates += [[b"\x22" * 32] * len(proof)]
        candidates += [[]]
        for cand in candidates:
            assert not merkle.verify_consistency(m, 24, old_root, new_root, cand)
            assert not vc.verify_consistency(m, 24, old_root, new_root, cand)
            cases += 1
    assert cases > 40


def test_no_forged_consistency_proof_is_accepted():
    """A rewrite admits no proof *from an anchor that covers it*.

    The subtlety this test pins, because it is a real limit of the scheme and not
    an implementation detail: a consistency proof from size m to size n asserts
    only that the first m leaves are unchanged. So if an entry at index 4 is
    altered, a root recorded at size 1 or size 4 is still a genuine prefix of the
    tampered tree -- those leaves really are untouched -- and a perfectly valid
    consistency proof exists from them.

    That is not a failure to detect tampering; it is the anchoring granularity
    doing its job. The rewrite becomes provable exactly when the recorded root is
    at a size *greater* than the altered index, because then the recorded root
    commits to the leaf that changed. The practical consequence is that the
    anchoring cadence bounds how far back a rewrite can be hidden, which is worth
    knowing before claiming the ledger is tamper-evident.

    Both directions are asserted: no proof verifies for m beyond the altered
    index, and a valid proof legitimately does exist for m at or below it.
    """
    d = data(18)
    altered_index = 4
    original_hashes = [merkle.leaf_hash(x) for x in d]

    tampered_d = list(d)
    tampered_d[altered_index] = b"leaf-4-rewritten"
    tampered_hashes = [merkle.leaf_hash(x) for x in tampered_d]
    assert tampered_hashes != original_hashes

    def candidates(m):
        return [
            merkle.consistency_proof(original_hashes, m, 18),   # from the original
            merkle.consistency_proof(tampered_hashes, m, 18),   # from the tampered
            [],
        ]

    # m > altered_index: the recorded root commits to the changed leaf, so the
    # rewrites must be provable and no candidate may verify.
    provable = 0
    for m in range(altered_index + 1, 18):
        old_root = merkle.root_from_hashes(original_hashes[:m])
        bad_new_root = merkle.root_from_hashes(tampered_hashes)
        for cand in candidates(m):
            assert not merkle.verify_consistency(m, 18, old_root, bad_new_root,
                                                 cand), f"server accepted m={m}"
            assert not vc.verify_consistency(m, 18, old_root, bad_new_root,
                                             cand), f"verifier accepted m={m}"
            provable += 1
    assert provable > 30

    # m <= altered_index: the recorded root is genuinely a prefix of the tampered
    # tree, so an honest proof exists. Asserting this keeps the limit above from
    # being read as a bug, and would catch an implementation that "fixed" it by
    # rejecting valid proofs.
    for m in range(1, altered_index + 1):
        old_root = merkle.root_from_hashes(original_hashes[:m])
        bad_new_root = merkle.root_from_hashes(tampered_hashes)
        honest = merkle.consistency_proof(tampered_hashes, m, 18)
        assert merkle.verify_consistency(m, 18, old_root, bad_new_root, honest)
        assert vc.verify_consistency(m, 18, old_root, bad_new_root, honest)


def test_a_forked_history_is_caught_not_merely_unproven():
    """Catching a fork means *rejecting*, not raising an error.

    An implementation that threw on a fork could be caught by a caller's
    ``except`` and turned into a pass; this asserts both implementations return
    a plain False, which no caller can mistake for success.
    """
    d = data(10)
    hashes = [merkle.leaf_hash(x) for x in d]
    original_root = merkle.root_from_hashes(hashes)

    forked = list(d)
    forked[1] = b"leaf-1-rewritten"
    forked_root = merkle.root_from_hashes([merkle.leaf_hash(x) for x in forked])

    proof = merkle.consistency_proof(hashes, 5, 10)
    assert merkle.verify_consistency(5, 10, original_root, forked_root,
                                    proof) is False
    assert vc.verify_consistency(5, 10, original_root, forked_root,
                                proof) is False


def test_verifier_rejects_out_of_range_indices():
    d = data(6)
    hashes = [merkle.leaf_hash(x) for x in d]
    root = merkle.root_from_hashes(hashes)
    for m in (-1, 6, 100):
        assert not vc.verify_inclusion(d[0], m, 6, [], root)
        assert not merkle.verify_inclusion(d[0], m, 6, [], root)


def test_canon_matches_the_server_for_awkward_objects():
    """The two canonicalisers must be byte-identical.

    Non-ASCII is the case that matters: ``ensure_ascii=True`` -- the json
    default -- would escape it, changing the bytes and invalidating every
    signature over any document containing an accent. It would present as
    tampering.
    """
    from logfirst.models import canon as server_canon

    cases = [
        {},
        {"a": 1, "b": [1, 2, 3]},
        {"z": "ünïcodé — em dash", "a": "日本語"},
        {"nested": {"deep": {"null": None, "t": True, "f": False}}},
        {"empty_list": [], "empty_str": "", "zero": 0},
        {"unicode_escape": "quote\" backslash\\ newline\n tab\t"},
        {"emoji": "🔐📄"},
    ]
    for obj in cases:
        assert vc.canon(obj) == server_canon(obj), obj


def test_canon_key_order_is_irrelevant():
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert vc.canon(a) == vc.canon(b)
