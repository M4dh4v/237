"""Post-quantum primitives, via liboqs.

Algorithm choices are fixed here and referenced by name everywhere else, so
there is exactly one place to audit:

``ML-KEM-768``  (FIPS 203) key encapsulation.
    Used to wrap a document's content key to a recipient, and -- separately --
    to wrap it to a client's *per-session ephemeral* key at open time.

``ML-DSA-65``   (FIPS 204) signatures.
    Every decryption request and every Signed Tree Head. This is the
    non-repudiation primitive.

``SLH_DSA_PURE_SHA2_128S`` (FIPS 205) signatures.
    Only for the periodically externalized ledger root anchor. It is hash-based
    and rests on the most conservative assumptions of the three -- no structured
    lattice hardness, just hash function security -- which is exactly what you
    want for the one artefact that has to be checkable a decade from now even if
    lattice assumptions weaken. It is slow and produces large signatures, and
    that is fine because anchors are written rarely (once per epoch, not once
    per open).

Why post-quantum at all: "harvest now, decrypt later". An adversary recording
ciphertext today does not need a quantum computer today; they need one before
the document stops mattering. For classified material with decades-long secrecy
requirements, that is a realistic timeline, and it applies with equal force to
the *signatures* -- an attribution that can be forged retroactively is not
evidence.
"""

from __future__ import annotations

import oqs

KEM = "ML-KEM-768"
SIG = "ML-DSA-65"
ANCHOR_SIG = "SLH_DSA_PURE_SHA2_128S"


def kem_keypair(alg: str = KEM) -> tuple[bytes, bytes]:
    """Return ``(public_key, secret_key)``."""
    with oqs.KeyEncapsulation(alg) as kem:
        pub = kem.generate_keypair()
        sec = kem.export_secret_key()
    return pub, sec


def kem_encap(pub: bytes, alg: str = KEM) -> tuple[bytes, bytes]:
    """Return ``(ciphertext, shared_secret)``."""
    with oqs.KeyEncapsulation(alg) as kem:
        return kem.encap_secret(pub)


def kem_decap(sec: bytes, ciphertext: bytes, alg: str = KEM) -> bytes:
    """Return the shared secret, or raise on a malformed ciphertext."""
    with oqs.KeyEncapsulation(alg, secret_key=sec) as kem:
        return kem.decap_secret(ciphertext)


def sig_keypair(alg: str = SIG) -> tuple[bytes, bytes]:
    """Return ``(public_key, secret_key)``."""
    with oqs.Signature(alg) as s:
        pub = s.generate_keypair()
        sec = s.export_secret_key()
    return pub, sec


def sign(sec: bytes, message: bytes, alg: str = SIG) -> bytes:
    with oqs.Signature(alg, secret_key=sec) as s:
        return s.sign(message)


def verify(pub: bytes, message: bytes, signature: bytes, alg: str = SIG) -> bool:
    """Verify, returning False rather than raising on malformed input.

    The deliberate consequence is that ``False`` means "not proven valid" and
    does not distinguish a wrong signature from a malformed key. Every caller
    here treats that as a denial, which is the fail-closed direction. Do not
    "improve" this into an exception without auditing the callers: a raised
    exception that escapes a gate is a crash, and a crash in a gate is
    indistinguishable from a denial only if the caller catches it -- whereas a
    ``False`` cannot be missed.
    """
    try:
        with oqs.Signature(alg) as s:
            return bool(s.verify(message, signature, pub))
    except Exception:
        return False


def fingerprint(pub: bytes, n: int = 16) -> str:
    """Short hex fingerprint of a public key, for display and log lines."""
    import hashlib
    return hashlib.sha256(pub).hexdigest()[:n]
