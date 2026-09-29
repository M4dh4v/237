"""Independent verification of a ledger entry, from public outputs alone.

This module exists because the authority that *issued* a decryption key is a
potential insider threat, and so is the ledger it writes to. A leak report that
says "the server says recipient X opened document Y" is worth nothing: the server
could be lying, or could have been made to lie. So every attribution this system
produces is re-derived here from data that can be checked without trusting the
running process:

* the raw leaf bytes,
* the Merkle inclusion proof and the Signed Tree Head they are checked against,
* the log's public key and the witnesses' public keys,
* the recipient's certificate public key.

Nothing in here consults the authority. Every function is pure, takes its inputs
as arguments, and would give the same answer run against a ledger dump years
later by someone who never had access to the server. That property is the whole
point of the exercise, and it is what ``verifier/`` re-implements separately:
the two implementations are deliberately duplicated so that a bug in one does
not silently validate the other.

The honesty rule this module enforces structurally
-------------------------------------------------
:attr:`VerificationReport.verified` is true only when *every* check passes.
There is no partial credit and no "probably fine" path. A caller cannot report an
attribution on the strength of the inclusion proof alone, because the flag they
would have to read is false until the signature, the proof, the STH and the
witness co-signatures all agree.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..crypto import pqc
from ..ledger import merkle
from ..models import STH, DecryptionRequest

# The kinds of leaf this ledger carries. An entry that is not a decryption
# request must never be presented as one.
KIND_DECRYPTION = "decryption-request"


@dataclass
class VerificationReport:
    """Per-check results for one ledger entry. Every field is a fact, not a
    score."""

    index: int
    kind: str = ""
    request_signature_ok: bool = False
    inclusion_ok: bool = False
    sth_signature_ok: bool = False
    witnesses_ok: list[str] = field(default_factory=list)
    witnesses_bad: list[str] = field(default_factory=list)
    witnesses_missing: list[str] = field(default_factory=list)
    witness_quorum: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def witness_quorum_ok(self) -> bool:
        """Did at least ``witness_quorum`` known witnesses co-sign this head?"""
        return len(self.witnesses_ok) >= self.witness_quorum > 0

    @property
    def witnesses_disagree(self) -> bool:
        """A known witness whose signature over this head does not verify.

        This is the tamper signal: a witness that signed a *different* tree at
        this size, or a STH whose fields were altered after signing.
        """
        return bool(self.witnesses_bad)

    @property
    def verified(self) -> bool:
        """True only if every check passed. No partial credit."""
        return (self.kind == KIND_DECRYPTION
                and self.request_signature_ok
                and self.inclusion_ok
                and self.sth_signature_ok
                and self.witness_quorum_ok
                and not self.witnesses_bad)

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "request_signature_ok": self.request_signature_ok,
            "inclusion_ok": self.inclusion_ok,
            "sth_signature_ok": self.sth_signature_ok,
            "witnesses_ok": self.witnesses_ok,
            "witnesses_bad": self.witnesses_bad,
            "witnesses_missing": self.witnesses_missing,
            "witness_quorum": self.witness_quorum,
            "witness_quorum_ok": self.witness_quorum_ok,
            "notes": self.notes,
            "verified": self.verified,
        }


def parse_leaf(leaf_data: bytes) -> dict:
    """Parse a leaf into ``{"kind", "request", "source_ip"}``.

    Raises ``ValueError`` on anything that is not a decryption-request leaf --
    the caller must not fall back to treating an arbitrary leaf as one.
    """
    obj = json.loads(leaf_data.decode("utf-8"))
    if not isinstance(obj, dict) or obj.get("kind") != KIND_DECRYPTION:
        raise ValueError(f"not a {KIND_DECRYPTION} leaf: "
                         f"{obj.get('kind') if isinstance(obj, dict) else type(obj)}")
    req = obj.get("request")
    if not isinstance(req, dict):
        raise ValueError("decryption leaf has no request object")
    return obj


def request_from_leaf(leaf_data: bytes) -> DecryptionRequest:
    """Rebuild the :class:`DecryptionRequest` a leaf commits to.

    Rebuilt from the committed bytes rather than from anything the server hands
    us separately, so the signature check below is over exactly what is in the
    log.
    """
    obj = parse_leaf(leaf_data)
    r = obj["request"]
    return DecryptionRequest(
        doc_id=r["doc_id"], recipient_id=r["recipient_id"], nonce=r["nonce"],
        timestamp=r["timestamp"], device_fp=r["device_fp"],
        ephemeral_kem_pub=r["ephemeral_kem_pub"], sig=r.get("sig", ""))


def verify_entry(index: int, leaf_data: bytes, inclusion_proof: list[bytes],
                 sth: STH, log_pub: bytes, witness_pubs: dict[str, bytes],
                 recipient_pub: bytes, witness_quorum: int = 2
                 ) -> VerificationReport:
    """Run every check for one ledger entry.

    ``witness_pubs`` maps witness id to ML-DSA public key. Witnesses in that map
    which did not sign are reported in ``witnesses_missing`` -- not as failures,
    since a witness may legitimately have been down, but the caller needs to know
    how many independent machines actually attested.
    """
    rep = VerificationReport(index=index, witness_quorum=witness_quorum)

    try:
        leaf_obj = parse_leaf(leaf_data)
        rep.kind = leaf_obj["kind"]
    except (ValueError, json.JSONDecodeError) as exc:
        rep.notes.append(f"leaf is not a decryption request: {exc}")
        return rep

    # 1. The recipient's own signature over the request. This is the
    #    non-repudiation claim: the ephemeral key in here is the one the content
    #    key was wrapped to, and it is covered by the signature, so the recipient
    #    cannot later claim the wrapped key was meant for someone else.
    dr = request_from_leaf(leaf_data)
    rep.request_signature_ok = pqc.verify(recipient_pub, dr.tbs(),
                                          bytes.fromhex(dr.sig or ""))

    # 2. Inclusion: recompute the leaf hash from the committed bytes and fold the
    #    proof up to the root the STH claims.
    rep.inclusion_ok = merkle.verify_inclusion(
        leaf_data, index, sth.tree_size, inclusion_proof,
        bytes.fromhex(sth.root_hash))

    # 3. The log's own signature over the head.
    rep.sth_signature_ok = pqc.verify(log_pub, sth.tbs(),
                                      bytes.fromhex(sth.log_sig or ""))

    # 4. Each witness, independently. A witness signature that is present but
    #    does not verify is reported separately from one that is absent: the
    #    first is evidence of tampering or equivocation, the second is not.
    for wid, pub in witness_pubs.items():
        sig = sth.witness_sigs.get(wid)
        if not sig:
            rep.witnesses_missing.append(wid)
            continue
        if pqc.verify(pub, sth.tbs(), bytes.fromhex(sig)):
            rep.witnesses_ok.append(wid)
        else:
            rep.witnesses_bad.append(wid)

    if rep.witnesses_bad:
        rep.notes.append(
            "witness signature(s) do not verify against this head: "
            + ", ".join(rep.witnesses_bad)
            + " -- either the head was altered after signing or a witness "
              "signed a different tree at this size")
    return rep


def check_against_anchor(sth: STH, anchors: list[dict]) -> dict:
    """Compare a head against previously externalized roots.

    Two things can go wrong and they are different:

    * our tree is *behind* an anchored root -- we are being shown an old view
      (rollback), or
    * our tree claims a size we already anchored with a different root
      (fork).

    Returns a dict describing which, so the caller can say so precisely rather
    than reporting a generic "mismatch".
    """
    out = {"checked": 0, "rollback": False, "fork": False,
           "highest_anchored": 0, "detail": ""}
    at_size = [a for a in anchors if a.get("tree_size") == sth.tree_size]
    out["checked"] = len(anchors)
    out["highest_anchored"] = max((a.get("tree_size", 0) for a in anchors),
                                  default=0)
    if sth.tree_size < out["highest_anchored"]:
        out["rollback"] = True
        out["detail"] = (f"head is at size {sth.tree_size} but size "
                         f"{out['highest_anchored']} was already externalized")
    for a in at_size:
        if a.get("root_hash") != sth.root_hash:
            out["fork"] = True
            out["detail"] = (f"size {sth.tree_size} was anchored with root "
                             f"{a.get('root_hash', '')[:16]}..., this head "
                             f"claims {sth.root_hash[:16]}...")
    return out
