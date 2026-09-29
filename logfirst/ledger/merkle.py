"""RFC 6962 Merkle tree hashing with inclusion and consistency proofs.

Pure functions over a list of leaf *data* byte strings. No storage here — the log
(``ledger/log.py``) owns persistence; this module owns the math so it can be unit
tested against the RFC 6962 known-answer vectors.
"""
from __future__ import annotations

import hashlib
from typing import List

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def leaf_hash(data: bytes) -> bytes:
    """MTH of a single leaf: SHA256(0x00 || data)."""
    return _sha256(LEAF_PREFIX + data)


def node_hash(left: bytes, right: bytes) -> bytes:
    """Interior node: SHA256(0x01 || left || right)."""
    return _sha256(NODE_PREFIX + left + right)


def _largest_power_of_two_lt(n: int) -> int:
    """Largest power of two strictly less than n (n >= 2)."""
    k = 1
    while k << 1 < n:
        k <<= 1
    return k


def root_from_hashes(hashes: List[bytes]) -> bytes:
    """Merkle Tree Hash over a list of already-computed leaf hashes."""
    n = len(hashes)
    if n == 0:
        return _sha256(b"")  # MTH({}) = SHA256()
    if n == 1:
        return hashes[0]
    k = _largest_power_of_two_lt(n)
    return node_hash(root_from_hashes(hashes[:k]), root_from_hashes(hashes[k:]))


def merkle_root(leaves: List[bytes]) -> bytes:
    """Merkle Tree Hash over a list of raw leaf data."""
    return root_from_hashes([leaf_hash(d) for d in leaves])


def inclusion_proof(hashes: List[bytes], m: int) -> List[bytes]:
    """Audit path PATH(m, D[n]) proving leaf index m is in the tree of leaf hashes."""
    n = len(hashes)
    if not 0 <= m < n:
        raise IndexError(f"leaf index {m} out of range for tree size {n}")
    if n == 1:
        return []
    k = _largest_power_of_two_lt(n)
    if m < k:
        return inclusion_proof(hashes[:k], m) + [root_from_hashes(hashes[k:])]
    return inclusion_proof(hashes[k:], m - k) + [root_from_hashes(hashes[:k])]


def verify_inclusion(leaf_data: bytes, m: int, n: int, proof: List[bytes], root: bytes) -> bool:
    """Recompute the root from a leaf + audit path and compare (RFC 6962 s2.1.1)."""
    if not 0 <= m < n:
        return False
    node = leaf_hash(leaf_data)
    fn, sn = m, n - 1
    idx = 0
    for sibling in proof:
        if fn % 2 == 1 or fn == sn:
            node = node_hash(sibling, node)
            while not (fn == 0 or fn % 2 == 1):
                fn >>= 1
                sn >>= 1
        else:
            node = node_hash(node, sibling)
        fn >>= 1
        sn >>= 1
        idx += 1
    return fn == 0 and node == root


def consistency_proof(hashes: List[bytes], m: int, n: int) -> List[bytes]:
    """PROOF(m, D[n]): that the size-n tree is an append-only extension of size-m."""
    if not 0 < m < n:
        if m == n:
            return []
        raise ValueError(f"consistency requires 0 < m < n, got m={m} n={n}")
    return _subproof(m, hashes[:n], True)


def _subproof(m: int, hashes: List[bytes], b: bool) -> List[bytes]:
    n = len(hashes)
    if m == n:
        return [] if b else [root_from_hashes(hashes)]
    k = _largest_power_of_two_lt(n)
    if m <= k:
        return _subproof(m, hashes[:k], b) + [root_from_hashes(hashes[k:])]
    return _subproof(m - k, hashes[k:], False) + [root_from_hashes(hashes[:k])]


def verify_consistency(m: int, n: int, old_root: bytes, new_root: bytes,
                       proof: List[bytes]) -> bool:
    """Verify a consistency proof between size m and size n (RFC 6962 s2.1.2)."""
    if m == n:
        return old_root == new_root and proof == []
    if m == 0 or m > n:
        return False
    if m & (m - 1) == 0:  # m is a power of two: old_root is implied, prepend it
        proof = [old_root] + proof
    if not proof:
        return False
    fn, sn = m - 1, n - 1
    while fn % 2 == 1:
        fn >>= 1
        sn >>= 1
    fr = sr = proof[0]
    for c in proof[1:]:
        if sn == 0:
            return False
        if fn % 2 == 1 or fn == sn:
            fr = node_hash(c, fr)
            sr = node_hash(c, sr)
            while not (fn == 0 or fn % 2 == 1):
                fn >>= 1
                sn >>= 1
        else:
            sr = node_hash(sr, c)
        fn >>= 1
        sn >>= 1
    return fn == 0 and fr == old_root and sr == new_root
