"""The one-time key lifecycle.

This module is the mechanical core of the pitch: *a document that cannot be
decrypted without first signing its own confession.* Two independent
properties have to hold, and they are worth separating because they defend
against different things.

**Property 1 -- the authority holds the only copy of K.**
At distribution time the sender generates a content key K, encrypts the
document with it, and wraps K under the *authority's* ML-KEM public key. The
recipient receives ciphertext and nothing else. No key material, no share of
key material, no "encrypted for you" blob the client could hoard. Compare the
older split-key design, where the recipient holds share A in a wrapped blob and
the authority holds share B: there, a client that never comes back online still
possesses a key share, and the security argument has to be about the *split*
rather than about access. Here there is no share to hold. The only way to
recover K is to ask the authority, and the authority is built to refuse unless
the request has already been committed to the ledger.

**Property 2 -- every response is inert outside its own session.**
Each open carries a fresh client-generated ML-KEM keypair. The authority wraps
K to that ephemeral public key and returns it. An adversary who records the
response, or who compromises the authority later and reads the response log,
holds a ciphertext addressed to a private key that was destroyed when the
client's session ended. This is why the ephemeral public key travels *inside*
the recipient's signed request body: an attacker who could substitute their own
ephemeral key in transit would redirect the response to themselves, and the
signature is what prevents that.

Neither property is worth much alone. Property 1 without 2 means a single
captured response leaks K forever. Property 2 without 1 means the recipient
already has K and never needs to ask. Together they are what make the ledger
append a genuine precondition for decryption rather than a logging side effect.
"""

from __future__ import annotations

from . import aead
from . import pqc
from .kdf import wrap_key_from_ss


def seal_content_key(server_kem_pub: bytes, content_key: bytes) -> dict:
    """Wrap ``content_key`` under the authority's KEM public key.

    Called once per document, at distribution. The result is what the authority
    stores; it is the only copy of K that exists anywhere.
    """
    kem_ct, ss = pqc.kem_encap(server_kem_pub)
    wk = wrap_key_from_ss(ss)
    nonce, wrapped = aead.encrypt(wk, content_key)
    return {"kem_alg": pqc.KEM, "kem_ct": kem_ct.hex(),
            "nonce": nonce.hex(), "wrapped_key": wrapped.hex()}


def unseal_content_key(server_kem_sec: bytes, envelope: dict) -> bytes:
    """Recover K. Only the authority's private key can do this.

    Raises on a malformed envelope rather than returning a wrong key, so a
    caller cannot accidentally proceed with garbage.
    """
    ss = pqc.kem_decap(server_kem_sec, bytes.fromhex(envelope["kem_ct"]),
                       envelope.get("kem_alg", pqc.KEM))
    wk = wrap_key_from_ss(ss)
    return aead.decrypt(wk, bytes.fromhex(envelope["nonce"]),
                        bytes.fromhex(envelope["wrapped_key"]))


def wrap_for_session(client_ephemeral_pub: bytes, content_key: bytes) -> dict:
    """Re-wrap K to a client's per-session ephemeral key.

    The authority calls this *after* the ledger commit, never before. The AAD
    binds the ciphertext to the purpose string so a blob produced here cannot
    be confused with any other wrapped key in the system.
    """
    kem_ct, ss = pqc.kem_encap(client_ephemeral_pub)
    wk = wrap_key_from_ss(ss)
    nonce, wrapped = aead.encrypt(wk, content_key, aad=b"logfirst-one-time-key")
    return {"kem_alg": pqc.KEM, "kem_ct": kem_ct.hex(),
            "nonce": nonce.hex(), "wrapped_key": wrapped.hex()}


def unwrap_session(client_ephemeral_sec: bytes, payload: dict) -> bytes:
    """Client side: recover K from the one-time blob.

    The caller must discard ``client_ephemeral_sec`` immediately after this
    returns -- and discard K as soon as the document is decrypted. The client
    library does both; see client/node.py.
    """
    ss = pqc.kem_decap(client_ephemeral_sec, bytes.fromhex(payload["kem_ct"]),
                       payload.get("kem_alg", pqc.KEM))
    wk = wrap_key_from_ss(ss)
    return aead.decrypt(wk, bytes.fromhex(payload["nonce"]),
                        bytes.fromhex(payload["wrapped_key"]),
                        aad=b"logfirst-one-time-key")
