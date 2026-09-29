"""AES-256-GCM authenticated encryption for bulk document content.

GCM rather than a non-AEAD mode because the ciphertext must be tamper-evident on
its own: a recipient who receives a modified document should get an
authentication failure, not a silently corrupted plaintext. The document id is
passed as AAD so a ciphertext cannot be replayed under a different document's
identity.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_LEN = 12
KEY_LEN = 32


def gen_key() -> bytes:
    """A fresh 256-bit content key."""
    return AESGCM.generate_key(bit_length=256)


def encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
    """Return ``(nonce, ciphertext||tag)``."""
    if len(key) != KEY_LEN:
        raise ValueError("AES-256-GCM requires a 32-byte key")
    nonce = os.urandom(NONCE_LEN)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes = b"") -> bytes:
    """Return the plaintext, or raise ``InvalidTag`` on tamper or wrong key."""
    return AESGCM(key).decrypt(nonce, ciphertext, aad)
