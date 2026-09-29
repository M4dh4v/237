"""Verifying a ledger evidence bundle.

A *bundle* is a self-contained JSON export of everything a third party needs to
check an attribution without access to the server, its database, or its code::

    {
      "version": 1,
      "log_pub": "<hex>",                        # the log's ML-DSA public key
      "witness_pubs": {"w1": "<hex>", ...},      # each witness's ML-DSA public key
      "witness_quorum": 2,
      "anchor_pub": "<hex>",                     # SLH-DSA key that signed anchors
      "head": { "tree_size": ..., "root_hash": ..., "timestamp": ...,
                "log_sig": "<hex>", "witness_sigs": {...} },
      "entries": [
        {
          "index": 12,
          "leaf": { ... },                       # the exact committed object
          "inclusion_proof": ["<hex>", ...],
          "sth": { ...the head as of this entry's commit... },
          "consistency_to_head": ["<hex>", ...],
          "recipient_id": "alice",
          "recipient_pub": "<hex>"               # from alice's certificate
        }
      ],
      "anchors": [ { "tree_size":…, "root_hash":…, "timestamp":…, "alg":…,
                     "anchor_pub":…, "anchor_sig":…,
                     "consistency_to_head": ["<hex>", ...] } ]
    }

The bundle is a chain, and every arrow is re-derived here:

    anchor root --consistency--> head <--consistency-- entry head
                                   |                       |
                           log sig + witness sigs    inclusion proof

The entry head is the one that existed when the entry was committed, so the
inclusion proof is checked against the head the witnesses co-signed *then*,
rather than against today's head, which would prove something weaker. The
consistency proofs then carry that head forward to the anchor.

The bundle carries the leaf as a JSON *object*, not as pre-serialised bytes, so
the verifier re-runs the canonicalisation itself. If the server's ``canon`` and
this one disagree, the hash comes out wrong and verification fails -- which is
the intended outcome, because a bundle that only verifies under the producer's
own serialiser has not been independently checked at all.

Exit codes are the interface, since this is meant to be scriptable:

===  ==================================================================
 0   verified: every entry sound, every anchor consistent with the head
 1   verification failed (the report says which check and why)
 2   the bundle could not be read or is malformed
 3   entries verified, but no anchor was offered -- history not checked
===  ==================================================================

Exit code 3 exists because 0 and 1 would both be misleading there. The
signatures, proofs and witness quorums all hold, so calling it a forgery would
be wrong; but nothing was checked against a root that left the building, so an
authority that rewrote its ledger *before* the bundle was taken would pass. That
is a weaker claim and it gets its own code. An anchor that was present and
*failed* is exit 1, not 3: that is a positive finding of inconsistency, not a
gap in the evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

from . import core

MAGIC_SIG = "ML-DSA-65"
MAGIC_ANCHOR_SIG = "SLH_DSA_PURE_SHA2_128S"

# The three fields a Signed Tree Head commits to. Kept as a tuple so the order
# of construction is fixed and visible -- canon sorts keys, but building the
# dict from an explicit tuple documents which fields are in scope.
STH_FIELDS = ("tree_size", "root_hash", "timestamp")

# The fields of a decryption request that are signed. `sig` is excluded because
# it is the signature over the rest.
REQUEST_FIELDS = ("doc_id", "recipient_id", "nonce", "timestamp", "device_fp",
                  "ephemeral_kem_pub")

# The fields of a recipient certificate that the CA signs. `ca_sig` is excluded.
# This list is the wire contract with `models.Certificate.tbs()`: a field added
# there and not here would make every certificate fail to verify, which is a
# loud failure, whereas a field dropped here would silently stop being covered.
CERT_FIELDS = ("recipient_id", "kem_alg", "sig_alg", "kem_pub", "sig_pub",
               "serial", "issued_at", "role")

ANCHOR_FIELDS = ("tree_size", "root_hash", "timestamp", "alg")


class BundleError(Exception):
    """The bundle is malformed -- not the same as 'the bundle is a forgery'."""


# --------------------------------------------------------------------------
# Signature verification
# --------------------------------------------------------------------------

def _oqs():
    try:
        import oqs
    except ImportError as e:                       # pragma: no cover
        raise BundleError(
            "liboqs-python is required to verify signatures (pip install "
            "liboqs-python, with the liboqs shared library installed)") from e
    return oqs


def verify_sig(pub_hex: str, message: bytes, sig_hex: str, alg: str) -> bool:
    """Verify one post-quantum signature. False on any error, including a
    malformed key or signature -- a verifier that raised here would tempt its
    caller into a try/except that defaults to 'valid'."""
    if not pub_hex or not sig_hex:
        return False
    try:
        with _oqs().Signature(alg) as v:
            return bool(v.verify(message, bytes.fromhex(sig_hex),
                                 bytes.fromhex(pub_hex)))
    except Exception:
        return False


def _consistent(m: int, m_root: str, n: int, n_root: str,
                proof: list[str] | None) -> bool:
    """Is the size-``m`` tree a prefix of the size-``n`` tree?

    ``proof is None`` is *not* the same as ``proof == []``: the first means no
    proof can exist in this direction, the second means the two sizes are equal
    and no proof is needed. Collapsing them would let a producer hide a rollback
    behind an empty list.
    """
    if proof is None:
        return False
    if m == n:
        return m_root == n_root and not proof
    if m > n or m <= 0:
        return False
    try:
        return core.verify_consistency(
            m, n, bytes.fromhex(m_root), bytes.fromhex(n_root),
            [bytes.fromhex(p) for p in proof])
    except ValueError:
        return False


def _head_status(head: dict, log_pub: str, witness_pubs: dict[str, str],
                 quorum: int) -> dict:
    """Check the bundle's top-level head: log signature and witness quorum.

    Every entry chains up to this head, so the witnesses' attestation of *this*
    head is what covers all of them. A head nobody co-signed would leave the
    whole chain resting on the log's word alone.
    """
    out = {"log_signature_ok": False, "witnesses_ok": [], "witnesses_bad": [],
           "witnesses_missing": [], "quorum_ok": False}
    try:
        tbs = core.canon({k: head[k] for k in STH_FIELDS})
    except KeyError:
        return out
    out["log_signature_ok"] = verify_sig(log_pub, tbs, head.get("log_sig", ""),
                                         MAGIC_SIG)
    sigs = head.get("witness_sigs") or {}
    for wid, pub in (witness_pubs or {}).items():
        sig = sigs.get(wid)
        if not sig:
            out["witnesses_missing"].append(wid)
        elif verify_sig(pub, tbs, sig, MAGIC_SIG):
            out["witnesses_ok"].append(wid)
        else:
            out["witnesses_bad"].append(wid)
    out["quorum_ok"] = len(out["witnesses_ok"]) >= quorum > 0
    return out


# --------------------------------------------------------------------------
# Per-entry checks
# --------------------------------------------------------------------------

@dataclass
class EntryReport:
    index: int
    kind: str = ""
    recipient_id: str = ""
    certificate_ok: bool = False
    request_signature_ok: bool = False
    inclusion_ok: bool = False
    sth_signature_ok: bool = False
    chained_to_head: bool = False
    witnesses_ok: list[str] = field(default_factory=list)
    witnesses_bad: list[str] = field(default_factory=list)
    witnesses_missing: list[str] = field(default_factory=list)
    witness_quorum: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (self.kind == "decryption-request"
                and self.certificate_ok
                and self.request_signature_ok
                and self.inclusion_ok
                and self.sth_signature_ok
                and self.chained_to_head
                and not self.witnesses_bad
                and len(self.witnesses_ok) >= self.witness_quorum > 0)

    def as_dict(self) -> dict:
        return {
            "index": self.index, "kind": self.kind,
            "recipient_id": self.recipient_id,
            "certificate_ok": self.certificate_ok,
            "request_signature_ok": self.request_signature_ok,
            "inclusion_ok": self.inclusion_ok,
            "sth_signature_ok": self.sth_signature_ok,
            "chained_to_head": self.chained_to_head,
            "witnesses_ok": self.witnesses_ok,
            "witnesses_bad": self.witnesses_bad,
            "witnesses_missing": self.witnesses_missing,
            "witness_quorum": self.witness_quorum,
            "ok": self.ok, "notes": self.notes,
        }


def verify_certificate(cert, recipient_id: str, recipient_pub: str,
                       ca_pub: str) -> tuple[bool, list[str]]:
    """Check the CA's signature, and that the certificate matches the entry.

    Without this the verifier only establishes "some key signed this request".
    The step that makes it "this *recipient's* key signed it" is checking the
    offline CA's signature over the identity-to-key binding -- because the
    authority is a potential insider threat and must not be able to substitute a
    key of its own choosing and have the verifier accept the result.

    Returns ``(ok, notes)``.
    """
    notes: list[str] = []
    if not isinstance(cert, dict):
        return False, ["entry carries no recipient certificate, so the signing "
                       "key is not bound to the recipient by the CA"]
    try:
        tbs = core.canon({k: cert[k] for k in CERT_FIELDS})
    except KeyError as e:
        return False, [f"recipient certificate is missing field {e}"]

    ok = True
    if not verify_sig(ca_pub, tbs, cert.get("ca_sig", ""), MAGIC_SIG):
        ok = False
        notes.append("recipient certificate is not signed by the CA")

    # The certificate must be *this* recipient's and must match the key the
    # request signature is checked against; otherwise a valid certificate for
    # somebody else would license any attribution.
    if cert.get("recipient_id") != recipient_id:
        ok = False
        notes.append(f"certificate is for {cert.get('recipient_id')!r}, but the "
                     f"entry claims {recipient_id!r}")
    if cert.get("sig_pub") != recipient_pub:
        ok = False
        notes.append("the key in the certificate is not the key the request "
                     "was checked against")
    return ok, notes


def verify_entry(entry: dict, log_pub: str, witness_pubs: dict[str, str],
                 witness_quorum: int, head: dict, ca_pub: str) -> EntryReport:
    rep = EntryReport(index=int(entry.get("index", -1)),
                      witness_quorum=witness_quorum)

    leaf_obj = entry.get("leaf")
    if not isinstance(leaf_obj, dict):
        rep.notes.append("entry has no leaf object")
        return rep
    rep.kind = leaf_obj.get("kind", "")

    # 1. Re-canonicalise the leaf here and hash it ourselves. This is the step
    #    that would catch a producer whose serialiser differs from ours.
    leaf_data = core.canon(leaf_obj)

    sth = entry.get("sth") or {}
    try:
        tree_size = int(sth["tree_size"])
        root = bytes.fromhex(sth["root_hash"])
    except (KeyError, ValueError) as e:
        rep.notes.append(f"malformed sth: {e}")
        return rep

    # 2. Inclusion: fold the proof from our own hash of the leaf to the root of
    #    the head this entry was committed under.
    proof = [bytes.fromhex(p) for p in entry.get("inclusion_proof", [])]
    rep.inclusion_ok = core.verify_inclusion(leaf_data, rep.index, tree_size,
                                             proof, root)

    # 3. The log's signature over that head. Redundant given step 5 -- the chain
    #    proof already pins this root -- but it catches an altered head
    #    timestamp, which the chain does not cover.
    sth_tbs = core.canon({k: sth[k] for k in STH_FIELDS if k in sth})
    rep.sth_signature_ok = verify_sig(log_pub, sth_tbs, sth.get("log_sig", ""),
                                      MAGIC_SIG)

    # 4. Witnesses, each independently. Present-but-invalid is separated from
    #    absent: the first is evidence of a fork, the second merely of a witness
    #    that was down.
    sigs = sth.get("witness_sigs") or {}
    for wid, pub in (witness_pubs or {}).items():
        sig = sigs.get(wid)
        if not sig:
            rep.witnesses_missing.append(wid)
        elif verify_sig(pub, sth_tbs, sig, MAGIC_SIG):
            rep.witnesses_ok.append(wid)
        else:
            rep.witnesses_bad.append(wid)
    if rep.witnesses_bad:
        rep.notes.append("witness signature(s) do not verify against this head: "
                         + ", ".join(rep.witnesses_bad))

    # 5. Chain this entry's head forward to the head the bundle tops out at.
    #    Steps 2 and 3 together prove only "this leaf is in *a* tree whose head
    #    the log signed". Without this, an entry lifted from a forked tree the
    #    log also signed would verify, because nothing connects the two. Here we
    #    require the commit-time head to be a prefix of the witnessed head.
    try:
        head_size = int(head["tree_size"])
        head_root = head["root_hash"]
    except (KeyError, ValueError) as e:
        rep.notes.append(f"bundle head is malformed: {e}")
        return rep
    rep.chained_to_head = _consistent(tree_size, sth.get("root_hash", ""),
                                      head_size, head_root,
                                      entry.get("consistency_to_head"))
    if not rep.chained_to_head:
        rep.notes.append(
            f"no valid consistency proof from this entry's head (size "
            f"{tree_size}) to the bundle head (size {head_size}); the entry "
            "may come from a forked tree")

    # 6. The recipient's certificate, then their signature. This is the
    #    non-repudiation claim, and it takes both steps: the CA's signature binds
    #    the identity to the key, and the recipient's signature binds the key to
    #    this exact request -- including the ephemeral KEM key the content key
    #    was wrapped to.
    req = leaf_obj.get("request")
    if not isinstance(req, dict):
        rep.notes.append("leaf has no request object")
        return rep
    rep.recipient_id = req.get("recipient_id", "")
    rep.certificate_ok, cert_notes = verify_certificate(
        entry.get("recipient_cert"), rep.recipient_id,
        entry.get("recipient_pub", ""), ca_pub)
    rep.notes.extend(cert_notes)

    try:
        req_tbs = core.canon({k: req[k] for k in REQUEST_FIELDS})
    except KeyError as e:
        rep.notes.append(f"request missing signed field: {e}")
        return rep
    rep.request_signature_ok = verify_sig(entry.get("recipient_pub", ""),
                                          req_tbs, req.get("sig", ""), MAGIC_SIG)
    return rep


# --------------------------------------------------------------------------
# Anchors
# --------------------------------------------------------------------------

@dataclass
class AnchorReport:
    checked: int = 0
    signed_ok: int = 0
    consistent: int = 0
    bad_signatures: list[int] = field(default_factory=list)
    inconsistent: list[dict] = field(default_factory=list)
    rollback: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.bad_signatures and not self.inconsistent \
            and not self.rollback

    def as_dict(self) -> dict:
        return {"checked": self.checked, "signed_ok": self.signed_ok,
                "consistent": self.consistent,
                "bad_signatures": self.bad_signatures,
                "inconsistent": self.inconsistent, "rollback": self.rollback,
                "ok": self.ok, "notes": self.notes}


def verify_anchors(head: dict, anchors: list[dict],
                   anchor_pub: str) -> AnchorReport:
    """Check each externalized root against the head the entries chain to.

    This is where a rewritten history is actually caught, and it is stronger
    than comparing roots at equal sizes. For every anchor we verify

    1. its own SLH-DSA signature, so the record is one the anchor key really
       produced, and
    2. a *consistency proof* from the anchored root to the bundle's head, so the
       history that left the building is provably a prefix of what we are being
       shown -- whatever the two sizes are.

    A producer who alters an old entry and rebuilds the tree can still produce a
    valid inclusion proof against its own rebuilt root. What it cannot do is
    produce a consistency proof from the root that was already externalized to
    its rebuilt head, because that would require the old entry to be unchanged.
    That is precisely the check performed here.

    Two distinct failures, reported separately because they mean different
    things:

    * *inconsistent* -- the anchor is validly signed but the head is not an
      extension of it. The ledger was rewritten.
    * *rollback* -- every anchor is ahead of the head we are being shown. We are
      looking at an old view of the log, perhaps because a newer one would
      expose something.
    """
    rep = AnchorReport()
    if not anchors:
        rep.notes.append(
            "no anchors in the bundle: nothing was checked against a root that "
            "left the building, so a rewritten history would go undetected. "
            "The entries themselves are verified, but that is a weaker claim")
        return rep

    try:
        head_size = int(head["tree_size"])
        head_root = head["root_hash"]
    except (KeyError, ValueError) as e:
        rep.notes.append(f"bundle head is malformed: {e}")
        return rep

    highest = 0
    for a in anchors:
        rep.checked += 1
        size = int(a.get("tree_size", -1))
        highest = max(highest, size)

        # 1. The anchor's own signature, over exactly the four fields that were
        #    signed. `alg` is inside the signed body, so a record re-labelled
        #    under a weaker scheme fails here rather than being reinterpreted.
        try:
            tbs = core.canon({k: a[k] for k in ANCHOR_FIELDS})
        except KeyError as e:
            rep.bad_signatures.append(size)
            rep.notes.append(f"anchor at size {size} is missing field {e}")
            continue
        if verify_sig(anchor_pub, tbs, a.get("anchor_sig", ""),
                      MAGIC_ANCHOR_SIG):
            rep.signed_ok += 1
        else:
            rep.bad_signatures.append(size)

        # 2. Consistency from the anchored root to the head.
        if size > head_size:
            continue                    # handled by the rollback check below
        if _consistent(size, a.get("root_hash", ""), head_size, head_root,
                       a.get("consistency_to_head")):
            rep.consistent += 1
        else:
            rep.inconsistent.append({
                "tree_size": size,
                "anchored_root": a.get("root_hash", ""),
                "head_root": head_root,
                "detail": f"size {size} was externalized with root "
                          f"{a.get('root_hash', '')[:16]}..., but the head at "
                          f"size {head_size} is not a consistent extension of "
                          "it -- an entry committed before that anchor was "
                          "altered or dropped"})

    if rep.bad_signatures:
        rep.notes.append("anchor(s) whose SLH-DSA signature does not verify: "
                         + ", ".join(str(x) for x in rep.bad_signatures))
    if highest > head_size:
        rep.rollback = True
        rep.notes.append(
            f"the bundle head is at size {head_size}, but size {highest} was "
            "already externalized -- this is a stale or truncated view of the "
            "log, and no proof in this direction is possible")
    return rep


# --------------------------------------------------------------------------
# Whole bundle
# --------------------------------------------------------------------------

def verify_bundle(bundle: dict) -> dict:
    """Run every check. Returns a report; never raises for a failed check.

    The report carries two verdicts, not one, because they answer different
    questions and a caller who collapses them will overstate what they know:

    * ``entries_ok`` -- every entry is cryptographically sound: the recipient's
      signature verifies, the leaf is in the tree its head claims, that head is
      signed by the log and co-signed by a witness quorum, and it chains to the
      bundle head.
    * ``anchored`` -- at least one externalized anchor was present and every
      anchor's consistency proof held. Only then has the *history* been checked
      against a root that left the building. Without it, an authority that
      rewrote its own ledger before this bundle was taken would go undetected,
      and the entries would still verify.

    ``ok`` requires both.
    """
    if not isinstance(bundle, dict):
        raise BundleError("bundle is not a JSON object")
    version = bundle.get("version")
    if version != 1:
        raise BundleError(f"unsupported bundle version {version!r}")

    log_pub = bundle.get("log_pub", "")
    witness_pubs = bundle.get("witness_pubs") or {}
    quorum = int(bundle.get("witness_quorum", 0))
    entries = bundle.get("entries") or []
    if not isinstance(entries, list) or not entries:
        raise BundleError("bundle contains no entries")

    # The head is mandatory. It is what the entries chain to and what the
    # witnesses attested to; a bundle without one would let a producer omit the
    # link that connects an entry to a witnessed tree, and an optional field
    # whose absence is treated as "skip this check" is an invitation to strip it.
    head = bundle.get("head")
    if not isinstance(head, dict):
        raise BundleError("bundle has no head object; entries cannot be "
                          "chained to a witnessed tree without it")
    # The CA's public key is what binds an identity to a signing key. It is
    # required for the same reason the head is: without it the verifier could
    # only establish "some key signed this", and a bundle that omitted it would
    # get a weaker check while still reporting success.
    ca_pub = bundle.get("ca_pub", "")
    if not ca_pub:
        raise BundleError("bundle has no ca_pub; the recipient certificates "
                          "could not be checked, so no attribution would be "
                          "bound to an identity")
    head_status = _head_status(head, log_pub, witness_pubs, quorum)

    reports = [verify_entry(e, log_pub, witness_pubs, quorum, head, ca_pub)
               for e in entries]
    anchors = verify_anchors(head, bundle.get("anchors") or [],
                             bundle.get("anchor_pub", ""))

    entries_ok = (all(r.ok for r in reports)
                  and head_status["log_signature_ok"]
                  and head_status["quorum_ok"]
                  and not head_status["witnesses_bad"])
    anchors_present = anchors.checked > 0
    anchored = anchors_present and anchors.ok
    return {
        "ok": entries_ok and anchored,
        "entries_ok": entries_ok,
        "anchors_present": anchors_present,
        "anchored": anchored,
        "head": head_status,
        "entries": [r.as_dict() for r in reports],
        "anchors": anchors.as_dict(),
        "summary": {
            "entries": len(reports),
            "verified": sum(1 for r in reports if r.ok),
            "witness_quorum": quorum,
        },
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _print_human(report: dict) -> None:
    s = report["summary"]
    h = report["head"]
    print(f"entries: {s['verified']}/{s['entries']} verified "
          f"(witness quorum {s['witness_quorum']})")
    print(f"  bundle head: log signature "
          f"{'yes' if h['log_signature_ok'] else 'NO'}, witnesses "
          f"{len(h['witnesses_ok'])} ok / {len(h['witnesses_bad'])} bad / "
          f"{len(h['witnesses_missing'])} absent")
    for wid in h["witnesses_bad"]:
        print(f"  HEAD WITNESS DISAGREES: {wid} did not sign this head")
    for e in report["entries"]:
        mark = "OK  " if e["ok"] else "FAIL"
        print(f"  [{mark}] index {e['index']:<5} kind={e['kind']:<20} "
              f"recipient={e['recipient_id'] or '?'}")
        for label, key in (("recipient certificate", "certificate_ok"),
                           ("recipient signature", "request_signature_ok"),
                           ("merkle inclusion", "inclusion_ok"),
                           ("log STH signature", "sth_signature_ok"),
                           ("chained to head", "chained_to_head")):
            print(f"           {label:<20} {'yes' if e[key] else 'NO'}")
        print(f"           {'witness co-signatures':<20} "
              f"{len(e['witnesses_ok'])} ok, {len(e['witnesses_bad'])} bad, "
              f"{len(e['witnesses_missing'])} absent")
        for n in e["notes"]:
            print(f"           note: {n}")

    a = report["anchors"]
    if a["checked"]:
        print(f"anchors: {a['signed_ok']}/{a['checked']} signatures ok, "
              f"{a['consistent']}/{a['checked']} consistent with the head"
              + ("  ROLLBACK DETECTED" if a["rollback"] else ""))
        for f in a["inconsistent"]:
            print(f"  INCONSISTENT: {f['detail']}")
    for n in a["notes"]:
        print(f"  note: {n}")

    # The headline has to distinguish "the entries check out" from "the history
    # checks out", because only the second protects against an authority that
    # rewrote its ledger before this bundle was taken. And "no anchor was
    # offered" must not read the same as "an anchor was offered and it
    # disagreed" -- the first is missing evidence, the second is evidence of
    # tampering.
    if report["ok"]:
        print("RESULT: VERIFIED (entries, and consistent with an externalized root)")
    elif report["entries_ok"] and not report["anchors_present"]:
        print("RESULT: ENTRIES VERIFIED, HISTORY NOT CHECKED "
              "(no anchor was offered -- a rewritten ledger would not have "
              "been caught)")
    elif report["entries_ok"]:
        print("RESULT: NOT VERIFIED (entries are sound, but an externalized "
              "root contradicts them -- see the anchor findings above)")
    else:
        print("RESULT: NOT VERIFIED")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="verify",
        description="Verify a logfirst evidence bundle without trusting the "
                    "server that produced it.")
    ap.add_argument("bundle", help="path to the bundle JSON (or '-' for stdin)")
    ap.add_argument("--json", action="store_true",
                    help="emit the full report as JSON")
    args = ap.parse_args(argv)

    try:
        if args.bundle == "-":
            bundle = json.load(sys.stdin)
        else:
            with open(args.bundle, "r", encoding="utf-8") as f:
                bundle = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"could not read bundle: {e}", file=sys.stderr)
        return 2

    try:
        report = verify_bundle(bundle)
    except BundleError as e:
        print(f"malformed bundle: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        _print_human(report)
    if report["ok"]:
        return 0
    # A distinct code for "the entries are sound but no anchor was offered at
    # all". Folding it into 0 would let a script treat an unchecked history as a
    # verified one; folding it into 1 would call a cryptographically intact
    # bundle a forgery. Note the asymmetry: an anchor that was offered and
    # *failed* is exit 1, because that is a finding, not a gap.
    if report["entries_ok"] and not report["anchors_present"]:
        return 3
    return 1


if __name__ == "__main__":                                 # pragma: no cover
    raise SystemExit(main())
