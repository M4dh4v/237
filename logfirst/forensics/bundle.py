"""Exporting an evidence bundle for third-party verification.

The authority is a potential insider threat, so an attribution it produces is
worth nothing *to the person being accused* unless it can be re-checked by
someone who does not trust the authority. This module writes out exactly what
such a check needs, and nothing that would let the authority's own code
participate in the check:

* the committed leaf **as a JSON object** -- not pre-hashed, so the verifier
  canonicalises and hashes it independently. If the two serialisers disagree,
  the hash differs, inclusion fails, and the disagreement surfaces as a failed
  verification instead of being hidden behind a shared helper.
* the inclusion proof, checked against the head the entry was committed under
  (the STH *at that tree size*, not the current one -- a proof for index 3
  against today's much larger tree is a proof of a different thing, and would
  let a verifier check the wrong claim without noticing).
* the log's public key, each witness's public key, and the witness quorum.
* the CA's public key and the recipient's **certificate**, so the request
  signature is checked against an identity the offline CA actually bound. Passing
  only the public key would leave the verifier able to establish "some key signed
  this" but not "this recipient's key signed it", and the authority is exactly
  the party that must not be trusted to assert the difference.
* the externalized anchors, so a rewrite of history can be caught against a
  value that left the building.

What deliberately is *not* here: the "expected" outcome, any score, any
pre-computed verdict. A bundle that told the verifier what to conclude would not
be evidence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ..ledger import merkle
from ..models import STH

VERSION = 1


class ExportError(Exception):
    """The bundle cannot be produced -- usually a missing public key."""


def _commit_size(index: int) -> int:
    """The tree size as of the commit of ``index``.

    Every append publishes a head at its own size, so the entry at index *i* was
    committed at size *i+1*. This is an assumption about the ledger's append
    discipline; it is stated once, here, because if that discipline ever changes
    this is the single place that has to change with it, and a silent mismatch
    would produce bundles that check the wrong head.
    """
    return index + 1


def _proof_hex(ledger, m: int, n: int) -> list[str] | None:
    """A consistency proof from size ``m`` to size ``n``, as hex.

    ``None`` means no proof exists in this direction (``m > n``), which is a
    rollback rather than an omission -- the caller and the verifier both need to
    tell those apart, so they are not both spelled ``[]``.
    """
    if m > n:
        return None
    if m == n:
        return []
    return [p.hex() for p in
            merkle.consistency_proof(ledger.leaf_hashes()[:n], m, n)]


class BundleExporter:
    """Builds bundles from a ledger plus the public keys they must be checked
    against.

    All keys are passed in rather than read from the authority's own store. The
    caller is expected to source them out of band -- witness keys from the
    witnesses' own state files, the log key from the ledger's bootstrap record,
    the anchor key from the pinned anchor file -- because a bundle that carried
    the authority's opinion of what the public keys are would let a compromised
    authority substitute its own key and verify cleanly.
    """

    def __init__(self, log_pub: bytes, witness_pubs: dict[str, bytes],
                 recipient_certs: dict[str, dict], witness_quorum: int,
                 anchor_pub: bytes | None = None, ca_pub: bytes | None = None):
        self.log_pub = log_pub
        self.witness_pubs = witness_pubs
        # Full certificates, not bare public keys. The verifier needs the CA's
        # signature over the identity-to-key binding; given only a key it could
        # check that *a* key signed the request but would have to take the
        # bundle's word for whose key it was.
        self.recipient_certs = recipient_certs
        self.witness_quorum = witness_quorum
        self.anchor_pub = anchor_pub
        self.ca_pub = ca_pub

    # -- construction helpers ---------------------------------------------

    @classmethod
    def from_deployment(cls, dep, log=None) -> "BundleExporter":
        """Wire an exporter from a :class:`~logfirst.data.deploy.Deployment`.

        Reads each witness's key from *its own* state file and the anchor key
        from the anchor keyfile, not from anything the authority publishes.
        """
        ledger = log or dep.open_log()
        anchor_pub = None
        keyfile = dep.path("anchors.jsonl") + ".key"
        if os.path.exists(keyfile):
            with open(keyfile, "r", encoding="utf-8") as f:
                anchor_pub = bytes.fromhex(json.load(f)["pub"])
        certs = {rid: rec["cert"] for rid, rec in dep.recipients().items()}
        return cls(log_pub=ledger.log_pub,
                   witness_pubs=dep.witness_pubs(),
                   recipient_certs=certs,
                   witness_quorum=dep.min_witnesses,
                   anchor_pub=anchor_pub, ca_pub=dep.ca_pub)

    # -- the export --------------------------------------------------------

    def entry(self, ledger, index: int, head_size: int) -> dict:
        """One entry, with the head it was committed under.

        The proof and the head are both taken at the size the entry was
        committed at, which is the point. An audit path computed over today's
        larger tree folds up to *today's* root, so checking it against the head
        from back then would fail, and checking it against today's head would
        prove only that the leaf is in the current tree -- not that any witness
        ever attested to a tree containing it. Taking both at the commit size
        means the verifier checks the leaf against the exact head the witnesses
        co-signed at that moment, and the ``consistency_to_head`` proof then
        carries that head forward to the one the bundle tops out at.

        ``sth_at`` returning nothing means the entry is in the ledger but has no
        witnessed head at its own size, i.e. the append that should have
        published one did not. That is reported, never papered over by
        substituting the current head.
        """
        leaf_data = ledger.get_leaf(index)
        try:
            leaf_obj = json.loads(leaf_data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ExportError(f"leaf {index} is not JSON: {e}") from e

        recipient_id = (leaf_obj.get("request") or {}).get("recipient_id", "")
        cert = self.recipient_certs.get(recipient_id)
        if cert is None:
            raise ExportError(
                f"no certificate for recipient {recipient_id!r} (entry "
                f"{index}); without it the bundle could only show that *some* "
                "key signed the request, not whose")

        size = _commit_size(index)
        sth = ledger.sth_at(size)
        if sth is None:
            raise ExportError(
                f"entry {index} has no witnessed head at size {size}; refusing "
                "to export against a different head, which would verify a "
                "claim the witnesses never attested to")

        proof = merkle.inclusion_proof(ledger.leaf_hashes()[:size], index)
        return {
            "index": index,
            "leaf": leaf_obj,
            "inclusion_proof": [p.hex() for p in proof],
            "sth": sth.to_dict(),
            # A proof that the head this entry was committed under is a prefix of
            # the head the bundle tops out at. Without it a verifier can check
            # the leaf against its own head but cannot connect that head to the
            # witnessed one, and an entry from a forked tree would pass.
            "consistency_to_head": _proof_hex(ledger, size, head_size),
            "recipient_id": recipient_id,
            "recipient_cert": cert,
            # Kept alongside the certificate so a reader can see at a glance
            # which key the signature below was checked against, and so that a
            # mismatch between the two is a check rather than an assumption.
            "recipient_pub": cert.get("sig_pub", ""),
        }

    def bundle(self, ledger, indexes: list[int],
               anchors: list[dict] | None = None) -> dict:
        """Build the bundle: entries, the head they chain to, and the anchors.

        The bundle is a *chain* rather than a bag of independent claims:

            anchor root  --consistency-->  head  <--consistency--  entry head
                                            |                       |
                                    log sig + witness sigs    inclusion proof

        Each arrow is a proof the verifier re-derives itself. The head is what
        the witnesses actually co-signed, so connecting an entry to the head and
        the head to an externalized anchor is what turns "this leaf hashes to
        the root of some tree" into "this leaf is in the tree the witnesses
        attested to, which extends the history someone recorded out of band".
        """
        if not indexes:
            raise ExportError("no entries requested")
        n = ledger.tree_size()
        for i in indexes:
            if i < 0 or i >= n:
                raise ExportError(f"index {i} out of range (tree size {n})")

        head = ledger.latest_sth()
        if head is None:
            raise ExportError("ledger has no Signed Tree Head; nothing to "
                              "anchor the bundle to")
        head_size = head.tree_size
        for i in indexes:
            if _commit_size(i) > head_size:
                raise ExportError(
                    f"entry {i} was committed at size {_commit_size(i)}, beyond "
                    f"the latest head at size {head_size}")

        out = {
            "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "alg": {"sig": "ML-DSA-65", "kem": "ML-KEM-768",
                    "anchor_sig": "SLH_DSA_PURE_SHA2_128S"},
            "log_pub": self.log_pub.hex(),
            "witness_pubs": {k: v.hex() for k, v in self.witness_pubs.items()},
            "witness_quorum": self.witness_quorum,
            "anchor_pub": self.anchor_pub.hex() if self.anchor_pub else "",
            "ca_pub": self.ca_pub.hex() if self.ca_pub else "",
            "head": head.to_dict(),
            "entries": [self.entry(ledger, i, head_size) for i in indexes],
            "anchors": self._anchor_records(ledger, anchors or [], head_size),
        }
        if not out["anchor_pub"]:
            # Not fatal -- the verifier reports the missing consistency check
            # rather than silently treating it as passed -- but say so here so
            # the caller can decide whether to go and find the pinned key.
            out["warnings"] = ["no anchor public key available: the verifier "
                               "will be unable to check consistency against a "
                               "previously externalized root"]
        return out

    @staticmethod
    def _anchor_records(ledger, anchors: list[dict], head_size: int) -> list[dict]:
        """Attach a consistency proof from each anchored root to the head.

        Adding fields to an anchor record does not disturb its signature: the
        signed body is exactly ``{tree_size, root_hash, timestamp, alg}`` and the
        verifier rebuilds it from those four fields alone. So the proof can ride
        alongside the record without being part of what the anchor key attested
        to -- which is correct, since the anchor was signed before this head
        existed.
        """
        out = []
        for a in anchors:
            rec = dict(a)
            m = int(a.get("tree_size", 0))
            if m < head_size:
                rec["consistency_to_head"] = _proof_hex(ledger, m, head_size)
            elif m == head_size:
                rec["consistency_to_head"] = []
            else:
                # The anchor is ahead of the head we hold: a rollback. There is
                # no proof in this direction, and the verifier reports it as
                # such rather than as a missing proof.
                rec["consistency_to_head"] = None
            out.append(rec)
        return out

    def save(self, ledger, indexes: list[int], path: str,
             anchors: list[dict] | None = None) -> dict:
        b = self.bundle(ledger, indexes, anchors)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(b, f, indent=1, sort_keys=True)
        return b


# --------------------------------------------------------------------------
# Cross-check against the system's own verifier
# --------------------------------------------------------------------------

def selfcheck(bundle: dict) -> dict:
    """Verify a bundle with the system's *own* evidence code.

    Used by the tests to assert the two implementations agree. It is not a
    substitute for ``verifier/``: this runs inside the package that produced the
    bundle, sharing its ``canon`` and its proof folding, so it can only show
    self-consistency. Where the two disagree, the independent verifier is right
    and this is the thing that is wrong.

    The certificate check is made here too, deliberately. If it were left out,
    a bundle with a forged certificate would pass ``selfcheck`` and fail the
    independent verifier, and the two would appear to disagree about a case
    where only one of them was actually looking.
    """
    from ..crypto import pqc
    from .evidence import verify_entry

    log_pub = bytes.fromhex(bundle["log_pub"])
    ca_pub = bytes.fromhex(bundle.get("ca_pub", "") or "")
    witness_pubs = {k: bytes.fromhex(v)
                    for k, v in (bundle.get("witness_pubs") or {}).items()}
    quorum = int(bundle.get("witness_quorum", 0))
    reports = []
    for e in bundle["entries"]:
        sth = STH.from_dict(e["sth"])
        rep = verify_entry(
            index=e["index"],
            leaf_data=_canon_bytes(e["leaf"]),
            inclusion_proof=[bytes.fromhex(p) for p in e["inclusion_proof"]],
            sth=sth, log_pub=log_pub, witness_pubs=witness_pubs,
            recipient_pub=bytes.fromhex(e["recipient_pub"]),
            witness_quorum=quorum)
        d = rep.as_dict()
        d["certificate_ok"] = _cert_ok(e, ca_pub)
        if not d["certificate_ok"]:
            d["verified"] = False
        reports.append(d)
    return {"ok": all(r["verified"] for r in reports), "entries": reports}


def _cert_ok(entry: dict, ca_pub: bytes) -> bool:
    """The CA's signature over the entry's certificate, plus the binding.

    Mirrors ``verifier.verify.verify_certificate``; kept separate on purpose so
    that the two implementations stay independent rather than sharing the check
    they exist to cross-examine.

    The recipient id to bind against is taken from the *committed request*, not
    from the bundle's top-level ``recipient_id`` field. Those are two different
    things -- the request is what is signed and hashed into the ledger, the other
    is a convenience copy -- and comparing against the copy would let a tampered
    bundle pass this check while the attribution named the wrong person.
    """
    from ..crypto import pqc
    from ..models import Certificate

    cert = entry.get("recipient_cert")
    if not isinstance(cert, dict) or not ca_pub:
        return False
    try:
        c = Certificate(**cert)
    except TypeError:
        return False
    if not pqc.verify(ca_pub, c.tbs(), bytes.fromhex(c.ca_sig or "")):
        return False
    req_id = ((entry.get("leaf") or {}).get("request") or {}).get("recipient_id")
    return (c.sig_pub == entry.get("recipient_pub")
            and c.recipient_id == req_id)


def _canon_bytes(obj) -> bytes:
    """Re-serialise a leaf object exactly as the log committed it."""
    from ..models import canon
    return canon(obj)
