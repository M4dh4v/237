"""HKDF-SHA256 derivations.

The ``info`` strings are domain separators and are part of the protocol, not
decoration. Two derivations from the same input keying material with different
``info`` produce unrelated keys; that is what stops a key derived for one
purpose being replayed in another. If you change one of these strings, every
artefact derived under the old one stops verifying -- intentionally, but again
it fails at verify time rather than import time.

Each constant is exported and imported by callers rather than being spelled out
at the call site, so a typo is an ImportError instead of a silent mismatch
between producer and consumer.
"""

from __future__ import annotations

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Wraps a content key under a KEM shared secret (document distribution, and the
# per-session re-wrap at open time).
INFO_WRAP = b"logfirst-wrap-v1"

# Derives the watermark seed from a *committed* leaf hash. The seed is therefore
# bound to the ledger entry: the same recipient opening the same document twice
# produces different seeds, because the two opens are different ledger entries.
INFO_WM_SEED = b"logfirst-wm-seed-v1"

# Masks the watermark codeword so the mark cannot be read off the page without
# the seed. See watermark/linguistic.py.
INFO_WM_KEYSTREAM = b"logfirst-wm-keystream-v1"


def hkdf(ikm: bytes, length: int = 32, salt: bytes | None = None,
         info: bytes = b"") -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt,
                info=info).derive(ikm)


def wrap_key_from_ss(shared_secret: bytes, info: bytes = INFO_WRAP) -> bytes:
    """The AEAD key that wraps a content key under a KEM shared secret."""
    return hkdf(shared_secret, 32, info=info)


def watermark_seed(leaf_hash: bytes) -> bytes:
    """Seed bound to a committed ledger entry."""
    return hkdf(leaf_hash, 32, info=INFO_WM_SEED)


def watermark_keystream(seed: bytes, nbits: int) -> bytes:
    """Expand a watermark seed into ``ceil(nbits/8)`` bytes of keystream."""
    return hkdf(seed, (nbits + 7) // 8, info=INFO_WM_KEYSTREAM)
