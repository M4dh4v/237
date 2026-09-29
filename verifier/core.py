"""Standalone verification primitives. Nothing here imports ``logfirst``.

This module is a deliberate re-implementation of the parts of the system that
produce evidence: canonical JSON, RFC 6962 hashing and proof folding, and the
signature checks. It shares no code with the server.

That duplication is the point. A verifier that called into the authority's own
hashing routine would confirm only that the authority is self-consistent -- a
bug in ``canon`` or in the proof fold would make a tampered ledger verify
cleanly, and the tool would report success while proving nothing. Written
separately, the two implementations have to agree for a bundle to verify, and
disagreement is itself the finding.

Dependencies are ``hashlib``, ``json``, ``base64`` and ``oqs``, nothing else.
There is no import of ``logfirst`` anywhere in this package, and
``tests/test_verifier_independence.py`` enforces that by walking the transitive
import graph in a subprocess rather than trusting this paragraph.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


# --------------------------------------------------------------------------
# Canonical serialization -- must match models.canon byte for byte
# --------------------------------------------------------------------------

def canon(obj: Any) -> bytes:
    """Canonical JSON: sorted keys, compact separators, UTF-8, no escaping.

    ``ensure_ascii=False`` matters: with it on, a document containing a non-ASCII
    character hashes to different bytes than the signer computed, and every
    signature over it fails. The failure would look like tampering.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------------------
# RFC 6962 Merkle tree
# --------------------------------------------------------------------------

def leaf_hash(data: bytes) -> bytes:
    """RFC 6962 leaf: SHA-256(0x00 || data).

    The 0x00/0x01 prefixes are what stop a second-preimage attack in which an
    interior node is presented as a leaf (or the reverse).
    """
    return hashlib.sha256(b"\x00" + data).digest()


def node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _largest_pow2_below(n: int) -> int:
    """Largest power of two strictly less than ``n`` (n must be > 1)."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def root_from_hashes(hashes: list[bytes]) -> bytes:
    """The tree head for a list of *leaf hashes*.

    RFC 6962 splits at the largest power of two below the count, which is what
    makes the tree append-only: every split point is a function of the size
    alone, so adding leaves never changes how the existing ones were combined.
    A naive "split in half" tree is also a Merkle tree but is not this one, and
    its proofs are not compatible.
    """
    n = len(hashes)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return hashes[0]
    k = _largest_pow2_below(n)
    return node_hash(root_from_hashes(hashes[:k]), root_from_hashes(hashes[k:]))


def merkle_root(leaves: list[bytes]) -> bytes:
    """Root over raw leaf *data* (hashed here)."""
    return root_from_hashes([leaf_hash(x) for x in leaves])


def verify_inclusion(leaf_data: bytes, index: int, tree_size: int,
                     proof: list[bytes], root: bytes) -> bool:
    """Recompute the root from one leaf and its audit path.

    Rejects out-of-range indices rather than clamping: an index of 10 in a tree
    of 5 leaves must be an error, not a silent read of leaf 4.

    The ``fn``/``sn`` walk is the standard RFC 6962 formulation. The inner
    ``while`` handles the case where the current node is a *right* child whose
    parent chain has already been consumed -- it skips the levels that the
    sibling provably covers, which is what stops the fold from consuming one
    proof element too many on ragged (non-power-of-two) trees.
    """
    if index < 0 or index >= tree_size:
        return False
    node = leaf_hash(leaf_data)
    fn, sn = index, tree_size - 1
    for p in proof:
        if sn == 0:
            return False                     # more proof than the tree justifies
        if fn & 1 or fn == sn:
            node = node_hash(p, node)
            while fn & 1 == 0 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            node = node_hash(node, p)
        fn >>= 1
        sn >>= 1
    return sn == 0 and node == root


def verify_consistency(m: int, n: int, old_root: bytes, new_root: bytes,
                       proof: list[bytes]) -> bool:
    """Check that the tree of size ``n`` extends the tree of size ``m``.

    This is the operation that makes tamper-evidence real. A ledger can always
    produce *a* root for whatever leaves it currently holds; what it cannot do,
    without being caught, is produce a new root that is a consistent extension
    of a root someone already recorded, after altering or dropping an earlier
    entry.

    The fold carries two accumulators at once -- ``old_node`` walking up to the
    old root and ``new_node`` walking up to the new one -- because the proof
    describes both trees simultaneously and they share most of their shape.
    Getting this wrong in the permissive direction would accept a forked
    ledger, so it is property-tested against the server's implementation over
    the full matrix of sizes up to 64, plus corrupted proofs, in
    tests/test_verifier_merkle.py.
    """
    if m == n:
        return old_root == new_root and not proof
    if m <= 0 or m > n:
        return False

    p = list(proof)
    if m & (m - 1) == 0:
        # m is a power of two, so its root is exactly the first node on the
        # path and the proof does not carry it; seed it here.
        p = [old_root] + p
    if not p:
        return False

    # Skip the levels the old root's own path already covers.
    fn, sn = m - 1, n - 1
    while fn % 2 == 1:
        fn >>= 1
        sn >>= 1

    old_node = new_node = p[0]
    for c in p[1:]:
        if sn == 0:
            return False                  # proof longer than the tree justifies
        if fn % 2 == 1 or fn == sn:
            old_node = node_hash(c, old_node)
            new_node = node_hash(c, new_node)
            while not (fn == 0 or fn % 2 == 1):
                fn >>= 1
                sn >>= 1
        else:
            new_node = node_hash(new_node, c)
        fn >>= 1
        sn >>= 1
    return fn == 0 and old_node == old_root and new_node == new_root
