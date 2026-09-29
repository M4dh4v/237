"""Periodic externalization of the ledger root, signed with SLH-DSA.

Purpose: give a verifier something to check against that does not require the
running server to be honest *or even alive*. Anchors are written to an
append-only JSONL file, and the root is also rendered as a short human-readable
code and a QR payload so it can be read off a screen, printed, or photographed
into a meeting minute. Once an observer has that value out of band, a later
rewrite of history has to contradict a number that left the building.

Why SLH-DSA here and ML-DSA everywhere else: this is the one artefact that has to
still be checkable a decade from now, by someone who trusts neither this system
nor current lattice assumptions. SLH-DSA is hash-based -- its security rests on
the hash function alone, the most conservative footing available in the NIST PQ
set. It is slow to sign and its signatures are large, which is exactly why it is
confined to this one rarely-written record rather than used per-request.

What an anchor does *not* prove: that the anchored root was ever witnessed, or
that the log contained anything in particular. It proves only that at time T,
the holder of the anchor key attested to this (size, root) pair. It is one link
in the chain, and the verifier report says so per-check rather than printing a
single global "OK".
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ..crypto import pqc
from ..models import canon


def short_code(root_hex: str) -> str:
    """A 20-hex-char, human-transcribable form of the root.

    Intended to be read aloud or written on a whiteboard. Truncation is
    deliberate: this is for eyeball comparison against an anchored value, and
    the full root is what the verifier actually checks.
    """
    s = root_hex[:20].upper()
    return "-".join(s[i:i + 4] for i in range(0, 20, 4))


class Anchorer:
    def __init__(self, anchor_pub: bytes, anchor_sec: bytes, path: str):
        self.anchor_pub = anchor_pub
        self.anchor_sec = anchor_sec
        self.path = path

    @classmethod
    def open(cls, path: str, keyfile: str | None = None) -> "Anchorer":
        keyfile = keyfile or (path + ".key")
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        if os.path.exists(keyfile):
            with open(keyfile, "r", encoding="utf-8") as f:
                k = json.load(f)
            return cls(bytes.fromhex(k["pub"]), bytes.fromhex(k["sec"]), path)
        pub, sec = pqc.sig_keypair(pqc.ANCHOR_SIG)
        with open(keyfile, "w", encoding="utf-8") as f:
            json.dump({"pub": pub.hex(), "sec": sec.hex(),
                       "alg": pqc.ANCHOR_SIG}, f)
        os.chmod(keyfile, 0o600)
        return cls(pub, sec, path)

    def _tbs(self, tree_size: int, root_hex: str, ts: str) -> bytes:
        # The algorithm name is inside the signed body so an anchor cannot be
        # reinterpreted under a weaker scheme by a verifier reading it later.
        return canon({"tree_size": tree_size, "root_hash": root_hex,
                      "timestamp": ts, "alg": pqc.ANCHOR_SIG})

    def anchor(self, tree_size: int, root_hex: str) -> dict:
        ts = datetime.now(timezone.utc).isoformat()
        rec = {
            "tree_size": tree_size,
            "root_hash": root_hex,
            "timestamp": ts,
            "alg": pqc.ANCHOR_SIG,
            "anchor_pub": self.anchor_pub.hex(),
            "short_code": short_code(root_hex),
        }
        rec["anchor_sig"] = pqc.sign(self.anchor_sec, self._tbs(tree_size, root_hex, ts),
                                     pqc.ANCHOR_SIG).hex()
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def records(self) -> list[dict]:
        return read_anchors(self.path)


def read_anchors(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def verify_anchor(rec: dict) -> bool:
    """Check an anchor record's own signature, using its embedded public key.

    Note the limitation, which callers must handle: this proves the record is
    internally consistent, *not* that ``anchor_pub`` is the real anchor key. A
    verifier has to obtain that public key out of band -- pinned at deployment,
    published, or read off the QR at the moment the anchor was taken. The
    standalone verifier takes it as a pinned argument for this reason.
    """
    tbs = canon({"tree_size": rec["tree_size"], "root_hash": rec["root_hash"],
                 "timestamp": rec["timestamp"], "alg": rec["alg"]})
    return pqc.verify(bytes.fromhex(rec["anchor_pub"]), tbs,
                      bytes.fromhex(rec["anchor_sig"]), rec["alg"])


def qr_payload(rec: dict) -> str:
    return f"{rec['tree_size']}:{rec['root_hash']}"


def ascii_qr(rec: dict) -> str:
    """Render the anchor as an ASCII QR block, if ``qrcode`` is installed.

    Optional by design: nothing in the trust chain depends on the QR, and a
    missing optional dependency must not take down the authority.
    """
    try:
        import qrcode
    except Exception:
        return ""
    qr = qrcode.QRCode(border=1)
    qr.add_data(qr_payload(rec))
    qr.make(fit=True)
    buf = []
    m = qr.get_matrix()
    for row in m:
        buf.append("".join("##" if c else "  " for c in row))
    return "\n".join(buf)
