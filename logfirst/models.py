"""Object model and canonical serialization.

Every signature and every hash in this system is computed over the output of
:func:`canon`, so this module is the byte-exact wire contract. Two rules follow
from that and are load-bearing:

1. **Field order matters.** Dataclass fields feed ``asdict()``, which feeds
   ``canon``. Reordering a field changes every signature over that type.
2. **The ``tbs()`` exclusion list is part of the format.** Each signed type
   strips exactly the field holding its own signature, and nothing else.

Changing either silently invalidates signatures produced by an older build --
which is the correct failure mode, but it fails *quietly* at verify time rather
than loudly at import time, so treat edits here as format changes.

Post-quantum rationale
----------------------
Signatures here are ML-DSA-65 (FIPS 204) and, for the rarely-written ledger
anchors, SLH-DSA-SHA2-128S (FIPS 205). Classified documents carry decades-long
secrecy requirements. The non-repudiation evidence produced today -- "this
recipient's key signed this request" -- has to remain unforgeable for as long as
the document stays classified, because the attribution may only be challenged
years later in a legal or administrative proceeding. A signature scheme that
falls to a cryptographically relevant quantum computer before then does not
merely weaken the system; it converts every past attribution into a claim the
accused can reasonably deny. That is the whole reason this is post-quantum
rather than "PQ later".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


def canon(obj: Any) -> bytes:
    """Canonical JSON bytes: sorted keys, compact separators, UTF-8.

    ``ensure_ascii=False`` is deliberate -- escaping non-ASCII would change the
    bytes for any document with non-Latin text, and the signature is over these
    bytes. Producer and verifier must agree exactly, so both call this function
    rather than re-implementing ``json.dumps``.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def h(b: bytes) -> str:
    return b.hex()


def unh(s: str) -> bytes:
    return bytes.fromhex(s)


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

@dataclass
class Certificate:
    """A recipient certificate issued by the offline CA.

    Binds two post-quantum public keys to an identity: an ML-KEM key (so a
    document's content key can be wrapped to this recipient) and an ML-DSA key
    (so this recipient's decryption requests are non-repudiable). The CA signs
    the binding; the CA's own key is offline and never touches the network.
    """
    recipient_id: str
    kem_alg: str
    sig_alg: str
    kem_pub: str          # hex, ML-KEM-768
    sig_pub: str          # hex, ML-DSA-65
    serial: str
    issued_at: str
    role: str = "recipient"
    ca_sig: str = ""      # hex, CA's ML-DSA signature over tbs()

    def tbs(self) -> bytes:
        d = asdict(self)
        d.pop("ca_sig", None)
        return canon(d)


@dataclass
class DeviceRecord:
    """A device bound to a recipient, signed by that recipient.

    The binding is what makes ``device_fp`` in a decryption request meaningful:
    without it, the fingerprint is a self-asserted string. With it, the claim
    "this device belongs to this recipient" is itself signed by the recipient
    and committed to the ledger at enrolment.
    """
    recipient_id: str
    device_id: str
    label: str
    platform: str
    hostname: str
    hw_id: str
    device_pub: str        # hex, ML-DSA-65 device key
    fingerprint: str       # hex, sha256 over attributes + device_pub
    enrolled_at: str
    kind: str = "device-enroll"
    recipient_sig: str = ""

    def tbs(self) -> bytes:
        d = asdict(self)
        d.pop("recipient_sig", None)
        return canon(d)

    def leaf_bytes(self) -> bytes:
        return canon(asdict(self))


# --------------------------------------------------------------------------
# The decryption request -- the leaf that the whole design turns on
# --------------------------------------------------------------------------

@dataclass
class DecryptionRequest:
    """A recipient's signed demand to open one document, for one session.

    ``ephemeral_kem_pub`` is what makes the response one-time. The client
    generates a fresh ML-KEM keypair for this single open, puts the public half
    here (inside the signed body, so it cannot be swapped in transit), and
    destroys the private half when the session ends. The authority wraps the
    content key to *that* key and no other, so a captured response is inert
    outside the session that requested it -- there is no long-lived recipient
    key that could decrypt a recording of the traffic.

    Because the field is inside ``tbs()``, an attacker who wants the authority
    to wrap the key to *their* key must produce a request signed by the
    recipient's ML-DSA private key. That is the non-repudiation property: the
    ledger entry and the recipient's own signature are the same object.
    """
    doc_id: str
    recipient_id: str
    nonce: str              # hex, per-session, client-chosen
    timestamp: str          # ISO-8601 UTC
    device_fp: str
    ephemeral_kem_pub: str  # hex, ML-KEM-768 public key, fresh per open
    sig: str = ""           # hex, ML-DSA-65 by the recipient over tbs()

    def tbs(self) -> bytes:
        d = asdict(self)
        d.pop("sig", None)
        return canon(d)

    def leaf_bytes(self) -> bytes:
        """The exact bytes appended to the ledger.

        Includes the signature -- the ledger entry *is* the signed request, so
        a verifier holding only the ledger can check the recipient's signature
        without trusting any database lookup.
        """
        return canon(asdict(self))


# --------------------------------------------------------------------------
# Transparency
# --------------------------------------------------------------------------

@dataclass
class STH:
    """Signed Tree Head: the log's committed claim about its own size and root.

    The log signs it (ML-DSA-65) and each witness co-signs it. A single log
    signature is the log talking about itself; the witness signatures are what
    make the claim survive the log's own operator turning hostile, because a
    witness will not sign an STH that contradicts one it already signed.
    """
    tree_size: int
    root_hash: str        # hex, sha256
    timestamp: str
    log_sig: str = ""     # hex, ML-DSA-65 by the log key
    witness_sigs: dict = field(default_factory=dict)   # witness_id -> hex

    def tbs(self) -> bytes:
        """Only these three fields are signed.

        The signature fields are excluded, which is what lets witnesses sign
        the same message the log signed, and lets a signature be added without
        invalidating the others.
        """
        return canon({"tree_size": self.tree_size,
                      "root_hash": self.root_hash,
                      "timestamp": self.timestamp})

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "STH":
        return cls(tree_size=d["tree_size"], root_hash=d["root_hash"],
                   timestamp=d["timestamp"], log_sig=d.get("log_sig", ""),
                   witness_sigs=dict(d.get("witness_sigs", {})))
