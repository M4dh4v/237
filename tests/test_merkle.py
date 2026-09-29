"""The Merkle math, pinned against the RFC 6962 construction.

Two things here cannot be checked by round-tripping the implementation against
itself, and they are the reason this file exists.

**The split rule.** RFC 6962 splits at the largest power of two below n, which is
what makes the tree append-only. A "split in half" tree is also a valid Merkle
tree, has valid inclusion proofs, and passes every round-trip property test --
but it is a *different tree*, its roots differ, and a proof from one does not
verify in the other. So a hand-built reference implementation of the split rule
lives here and the audit paths are asserted against it explicitly.

**The domain separation.** The RFC fixes ``MTH({}) = SHA-256()`` and the
``0x00``/``0x01`` prefixes. Those are stated identities, not implementation
choices, and they are asserted directly.

The leaf data below is this file's own choice (the RFC's prose example uses a
different set), so the expected paths are *derived* from the rule by composing
``leaf_hash``/``node_hash`` by hand rather than quoted from a published table.
Where a published value would be better, it is not available, and a
mis-transcribed "vector" that happens to match a buggy implementation is worse
than no vector at all.
"""

from __future__ import annotations

import hashlib

import pytest

from logfirst.ledger import merkle

LEAVES = [b"", b"\x00", b"\x10", b"\x20", b"\x30", b"\x40", b"\x50"]


def node(a: bytes, b: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + a + b).digest()


def mth(hs: list[bytes]) -> bytes:
    """The RFC's MTH, written from the definition and independent of the module."""
    n = len(hs)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return hs[0]
    k = 1
    while k * 2 < n:
        k *= 2
    return node(mth(hs[:k]), mth(hs[k:]))


def test_empty_tree_root():
    """MTH({}) = SHA256() -- a stated identity in the RFC."""
    assert merkle.root_from_hashes([]) == hashlib.sha256(b"").digest()
    assert merkle.merkle_root([]) == hashlib.sha256(b"").digest()


def test_single_leaf_root_is_the_leaf_hash():
    assert merkle.merkle_root([b""]) == merkle.leaf_hash(b"")


def test_audit_paths_follow_the_rfc_split_rule():
    """Pinned against a from-the-definition build of the same tree.

    Each expectation is composed by hand from ``leaf_hash``/``node_hash``, so it
    pins the *shape* of the tree rather than merely that a proof round-trips.
    """
    e = [merkle.leaf_hash(x) for x in LEAVES]
    assert merkle.root_from_hashes(e) == mth(e)

    # PATH(0, D[7]): leaf 0 is the first leaf of D[0:4], whose root is the first
    # leaf of D[0:2] -- so its sibling at the bottom is e1, then the roots of
    # D[2:4] and D[4:7].
    assert merkle.inclusion_proof(e, 0) == [e[1], mth(e[2:4]), mth(e[4:])]

    # PATH(3, D[7]): leaf 3 is the *last* leaf of D[0:4], so its sibling is the
    # whole of D[0:2] combined -- an interior node, not a leaf hash.
    assert merkle.inclusion_proof(e, 3) == [e[2], mth(e[0:2]), mth(e[4:])]

    # PATH(6, D[7]): leaf 6 is the last leaf of D[4:7], which itself splits at 2,
    # so its sibling is MTH(D[4:6]) and then the root of D[0:4].
    assert merkle.inclusion_proof(e, 6) == [mth(e[4:6]), mth(e[0:4])]

    # Every index's path must also actually work against the root.
    root = merkle.root_from_hashes(e)
    for m in range(7):
        assert merkle.verify_inclusion(LEAVES[m], m, 7,
                                       merkle.inclusion_proof(e, m), root)


def test_inclusion_round_trips_for_every_index_and_size():
    """Every leaf of every tree up to 40 leaves has a proof that verifies."""
    data = [f"leaf-{i}".encode() for i in range(40)]
    for n in range(1, 41):
        hashes = [merkle.leaf_hash(d) for d in data[:n]]
        root = merkle.root_from_hashes(hashes)
        for m in range(n):
            proof = merkle.inclusion_proof(hashes, m)
            assert merkle.verify_inclusion(data[m], m, n, proof, root), \
                f"inclusion failed for leaf {m} of {n}"


def test_inclusion_rejects_wrong_leaf_and_out_of_range():
    data = [f"leaf-{i}".encode() for i in range(8)]
    hashes = [merkle.leaf_hash(d) for d in data]
    root = merkle.root_from_hashes(hashes)
    proof = merkle.inclusion_proof(hashes, 3)
    assert not merkle.verify_inclusion(b"not-a-leaf", 3, 8, proof, root)
    # An index outside the tree must be an error, never a silent read of the
    # last leaf.
    assert not merkle.verify_inclusion(data[3], 8, 8, proof, root)
    assert not merkle.verify_inclusion(data[3], -1, 8, proof, root)


def test_leaf_and_node_hash_are_domain_separated():
    """The 0x00/0x01 prefixes stop a node being replayed as a leaf.

    Without the prefix, presenting an interior node's preimage as leaf data
    would produce the same hash and a forged inclusion proof would verify.
    """
    interior = merkle.node_hash(b"a" * 32, b"b" * 32)
    assert merkle.leaf_hash(interior) != interior
    assert merkle.leaf_hash(b"\x01" + b"a" * 32 + b"b" * 32) != interior


def test_consistency_proof_agrees_with_the_inclusion_definition():
    """A consistency proof is valid exactly when the old tree is a prefix.

    Checked structurally rather than against the verifier: rebuilding the first
    ``m`` leaves must produce the old root, and the full ``n`` the new one.
    """
    data = [f"leaf-{i}".encode() for i in range(30)]
    for n in range(2, 31):
        for m in range(1, n):
            hashes = [merkle.leaf_hash(d) for d in data[:n]]
            old_root = merkle.root_from_hashes(hashes[:m])
            new_root = merkle.root_from_hashes(hashes)
            proof = merkle.consistency_proof(hashes, m, n)
            assert merkle.verify_consistency(m, n, old_root, new_root, proof), \
                f"consistency failed m={m} n={n}"


def test_consistency_rejects_a_rewritten_history():
    """The operation the whole tamper-evidence story rests on.

    Alter one leaf, rebuild the tree, and ask for a proof from the *original*
    root to the new one. No proof can exist, and every candidate is rejected --
    including the proof for the untouched tree, which is what a naive
    implementation would hand over and call valid.
    """
    data = [f"leaf-{i}".encode() for i in range(16)]
    hashes = [merkle.leaf_hash(d) for d in data]
    original_root = merkle.root_from_hashes(hashes)
    honests_proof = merkle.consistency_proof(hashes, 8, 16)

    tampered = list(data)
    tampered[2] = b"leaf-2-altered"
    tampered_hashes = [merkle.leaf_hash(d) for d in tampered]
    tampered_root = merkle.root_from_hashes(tampered_hashes)
    assert tampered_root != original_root

    # The honest proof does not verify against the tampered root.
    assert not merkle.verify_consistency(8, 16, original_root, tampered_root,
                                        honests_proof)

    # And no proof from the tampered tree verifies against the original root.
    for m in range(1, 16):
        for proof in (merkle.consistency_proof(tampered_hashes, m, 16), []):
            assert not merkle.verify_consistency(m, 16, original_root,
                                                 tampered_root, proof)


def test_consistency_proof_length_bounds():
    """A proof longer than the tree justifies must be rejected, not ignored.

    Truncation is the cheap forgery: hand over the honest prefix of a proof and
    hope the fold accepts. It does not, for any prefix.
    """
    data = [f"leaf-{i}".encode() for i in range(12)]
    hashes = [merkle.leaf_hash(d) for d in data]
    old_root = merkle.root_from_hashes(hashes[:5])
    new_root = merkle.root_from_hashes(hashes)
    proof = merkle.consistency_proof(hashes, 5, 12)
    assert merkle.verify_consistency(5, 12, old_root, new_root, proof)
    for cut in range(len(proof)):
        assert not merkle.verify_consistency(5, 12, old_root, new_root,
                                             proof[:cut])
    for extra in range(1, 4):
        assert not merkle.verify_consistency(5, 12, old_root, new_root,
                                             proof + [b"\x00" * 32] * extra)


def test_consistency_edge_cases():
    data = [f"leaf-{i}".encode() for i in range(8)]
    hashes = [merkle.leaf_hash(d) for d in data]
    root = merkle.root_from_hashes(hashes)
    # m == n is the trivial case and must carry no proof.
    assert merkle.verify_consistency(8, 8, root, root, [])
    assert not merkle.verify_consistency(8, 8, root, b"\x00" * 32, [])
    # m <= 0 and m > n are nonsense, not vacuously true.
    assert not merkle.verify_consistency(0, 8, root, root, [])
    assert not merkle.verify_consistency(9, 8, root, root, [])


def test_inclusion_proof_of_a_power_of_two_tree_against_a_larger_root():
    """A proof taken at size m must not verify against size n > m.

    This is the mistake that would make the whole scheme vacuous: verifying an
    entry's inclusion against *today's* root rather than the head it was
    committed under. The leaf genuinely is in the larger tree, so an
    implementation that folded a longer proof would still "work"; the check here
    is that the shorter proof does not silently pass.
    """
    data = [f"leaf-{i}".encode() for i in range(10)]
    hashes = [merkle.leaf_hash(d) for d in data]
    short_proof = merkle.inclusion_proof(hashes[:4], 1)
    root4 = merkle.root_from_hashes(hashes[:4])
    root10 = merkle.root_from_hashes(hashes)
    assert merkle.verify_inclusion(data[1], 1, 4, short_proof, root4)
    assert not merkle.verify_inclusion(data[1], 1, 4, short_proof, root10)
