"""The verifier against a real bundle, and against every way of breaking one.

A verifier that accepts an honest bundle has demonstrated almost nothing. What
makes the tool worth having is the list of *mutations* it refuses, so this file
is mostly a table of forgeries, each one a thing an authority with write access
to its own ledger could plausibly do:

* alter a committed leaf in place -- the operator's own edit of history;
* swap the recipient's certificate key, to pin an attribution on someone else;
* swap the log's key for a key the operator controls;
* rebuild the tree around an altered entry and re-sign the head, which is the
  attack the Merkle proofs are *for* -- inclusion still verifies, so only the
  chain to the externalized anchor catches it;
* strip the anchor, or corrupt its signature, or re-label it under a weaker
  algorithm;
* show an old head, so that later entries are invisible;
* drop witness co-signatures until the quorum is not met.

Each case asserts the *specific* check that failed, not just a false verdict.
A mutation "caught" by the wrong check is a bug waiting to happen: it means the
check that should have caught it is broken and something else happened to fail
first.
"""

from __future__ import annotations

import copy
import json

import pytest

from logfirst.crypto import pqc
from logfirst.forensics.bundle import BundleExporter, ExportError, selfcheck
from logfirst.ledger import merkle
from logfirst.ledger.anchor import Anchorer
from logfirst.ledger.log import LedgerLog
from logfirst.ledger.witnesses import QuorumNotMet, WitnessQuorum
from verifier.verify import BundleError, verify_bundle

from tests.conftest import make_request, make_witnesses

N_ENTRIES = 6
ANCHOR_SIZE = 3


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """A ledger with 6 real entries, 3 witnesses, and one externalized root.

    Module-scoped because SLH-DSA signing (the anchor) is deliberately slow and
    the ledger contents are read-only for every test here.

    Each entry is a *different* recipient with a real CA-issued certificate.
    Reusing recipients would make "attribute the entry to another recipient's
    certificate" a no-op rather than the forgery it is meant to be.
    """
    from logfirst.crypto import ca as ca_mod

    root = tmp_path_factory.mktemp("bundle")
    witnesses = make_witnesses(root, 3)
    log = LedgerLog.open(str(root / "ledger.db"),
                         WitnessQuorum(list(witnesses), min_witnesses=2))

    ca = ca_mod.CA.create()
    certs, secs = {}, {}
    for i in range(N_ENTRIES):
        rid = f"u{i}"
        cert, secrets = ca_mod.enroll_recipient(ca, rid)
        certs[rid] = cert.__dict__
        secs[rid] = bytes.fromhex(secrets["sig_sec"])
        log.gated_append_for_decryption(
            make_request(rid, f"DOC-{i:04d}", sig_sec=secs[rid]).leaf_bytes(),
            "127.0.0.1")

    # Anchor a root that covers the first ANCHOR_SIZE entries. Anchoring *after*
    # every entry is written is what makes a later rewrite of any of them
    # provable; see test_verifier_merkle for why the size matters.
    anchorer = Anchorer.open(str(root / "anchors.jsonl"))
    anchor = anchorer.anchor(
        ANCHOR_SIZE,
        merkle.root_from_hashes(log.leaf_hashes()[:ANCHOR_SIZE]).hex())

    exporter = BundleExporter(
        log_pub=log.log_pub,
        witness_pubs={w.witness_id: w.signer.sig_pub for w in witnesses},
        recipient_certs=certs, witness_quorum=2, anchor_pub=anchorer.anchor_pub,
        ca_pub=ca.sig_pub)
    bundle = exporter.bundle(log, list(range(N_ENTRIES)), [anchor])
    return {"root": root, "witnesses": witnesses, "log": log, "certs": certs,
            "secs": secs, "anchorer": anchorer, "anchor": anchor,
            "exporter": exporter, "bundle": bundle, "ca": ca}


@pytest.fixture
def bundle(env):
    return copy.deepcopy(env["bundle"])


# --------------------------------------------------------------------------
# The honest case
# --------------------------------------------------------------------------

def test_honest_bundle_verifies(bundle):
    r = verify_bundle(bundle)
    assert r["ok"] is True
    assert r["entries_ok"] is True
    assert r["anchors_present"] is True
    assert r["anchored"] is True
    assert r["summary"]["verified"] == N_ENTRIES
    for e in r["entries"]:
        assert e["request_signature_ok"] and e["inclusion_ok"]
        assert e["sth_signature_ok"] and e["chained_to_head"]
        assert len(e["witnesses_ok"]) >= 2 and not e["witnesses_bad"]


def test_the_system_own_verifier_agrees(bundle):
    """The two implementations must not diverge on an honest bundle.

    When they do diverge, the independent one is the one to believe -- it is the
    one that shares no code with the producer. But a divergence on an *honest*
    bundle means one of them is broken, so it is a test failure either way.
    """
    assert selfcheck(bundle)["ok"] is True
    assert verify_bundle(bundle)["ok"] is True


# --------------------------------------------------------------------------
# Forgeries
# --------------------------------------------------------------------------

def _mutations():
    """(name, mutation, the check that must fail) triples."""
    def leaf(b, i=3):
        return b["entries"][i]["leaf"]["request"]

    return [
        ("alter the committed doc_id",
         lambda b: leaf(b).__setitem__("doc_id", "DOC-9999"),
         {"inclusion_ok", "request_signature_ok"}),
        ("alter the committed recipient_id",
         lambda b: leaf(b).__setitem__("recipient_id", "someone-else"),
         {"inclusion_ok", "request_signature_ok"}),
        ("alter the logged source_ip",
         lambda b: b["entries"][3]["leaf"].__setitem__("source_ip", "10.0.0.9"),
         {"inclusion_ok"}),
        ("zero the recipient's signature",
         lambda b: leaf(b).__setitem__("sig", "00" * 3309),
         {"inclusion_ok", "request_signature_ok"}),
        ("swap in a different ephemeral KEM key",
         lambda b: leaf(b).__setitem__("ephemeral_kem_pub", "ab" * 1184),
         {"inclusion_ok", "request_signature_ok"}),
        ("attribute the entry to another recipient's certificate",
         lambda b: b["entries"][3].__setitem__(
             "recipient_cert", b["entries"][0]["recipient_cert"]),
         {"certificate_ok", "request_signature_ok"}),
        ("swap only the public key, leaving the certificate",
         lambda b: b["entries"][3].__setitem__(
             "recipient_pub", b["entries"][0]["recipient_pub"]),
         {"certificate_ok", "request_signature_ok"}),
        ("forge a certificate with no CA signature",
         lambda b: b["entries"][3]["recipient_cert"].__setitem__("ca_sig", ""),
         {"certificate_ok"}),
        ("forge a certificate with a bogus CA signature",
         lambda b: b["entries"][3]["recipient_cert"].__setitem__(
             "ca_sig", "00" * 3309),
         {"certificate_ok"}),
        ("re-bind the certificate to a different recipient id",
         lambda b: b["entries"][3]["recipient_cert"].__setitem__(
             "recipient_id", "somebody-else"),
         {"certificate_ok"}),
        ("substitute a self-minted key inside the certificate",
         lambda b: b["entries"][3]["recipient_cert"].__setitem__(
             "sig_pub", "ab" * 1952),
         {"certificate_ok"}),
        ("swap the pinned CA key",
         lambda b: b.__setitem__("ca_pub", b["log_pub"]),
         {"certificate_ok"}),
        ("strip the certificate entirely",
         lambda b: b["entries"][3].pop("recipient_cert"),
         {"certificate_ok"}),
        ("corrupt an inclusion proof element",
         lambda b: b["entries"][3]["inclusion_proof"].__setitem__(0, "00" * 32),
         {"inclusion_ok"}),
        ("truncate an inclusion proof",
         lambda b: b["entries"][3]["inclusion_proof"].pop(),
         {"inclusion_ok"}),
        ("renumber an entry to point at another leaf",
         lambda b: b["entries"][3].__setitem__("index", 2),
         {"inclusion_ok"}),
        ("corrupt the chain proof to the head",
         lambda b: b["entries"][3]["consistency_to_head"].__setitem__(0,
                                                                     "00" * 32),
         {"chained_to_head"}),
        ("strip the chain proof to the head",
         lambda b: b["entries"][3].__setitem__("consistency_to_head", None),
         {"chained_to_head"}),
        ("alter the head a witness co-signed",
         lambda b: b["entries"][3]["sth"].__setitem__(
             "timestamp", "2020-01-01T00:00:00+00:00"),
         {"sth_signature_ok"}),
        ("corrupt one witness co-signature",
         lambda b: b["entries"][3]["sth"]["witness_sigs"].__setitem__(
             "w2", "00" * 3309),
         {"witnesses_bad"}),
        ("raise the required quorum above the witnesses available",
         lambda b: b.__setitem__("witness_quorum", 4),
         {"quorum"}),
        ("swap the log's key for a witness's",
         lambda b: b.__setitem__("log_pub", b["witness_pubs"]["w1"]),
         {"sth_signature_ok", "head_signature"}),
        ("corrupt the head's own signature",
         lambda b: b["head"].__setitem__("log_sig", "00" * 3309),
         {"head_signature"}),
        ("strip the head's witness co-signatures",
         lambda b: b["head"].__setitem__("witness_sigs", {}),
         {"quorum"}),
        ("rewrite the head's root",
         lambda b: b["head"].__setitem__("root_hash", "ee" * 32),
         {"chained_to_head", "anchor_inconsistent"}),
        ("corrupt the anchor's signature",
         lambda b: b["anchors"][0].__setitem__("anchor_sig", "00" * 7856),
         {"anchor_signature"}),
        ("rewrite an externalized root",
         lambda b: b["anchors"][0].__setitem__("root_hash", "ff" * 32),
         {"anchor_inconsistent"}),
        ("corrupt the anchor's consistency proof",
         lambda b: b["anchors"][0]["consistency_to_head"].__setitem__(0,
                                                                      "00" * 32),
         {"anchor_inconsistent"}),
        ("strip the anchor's consistency proof",
         lambda b: b["anchors"][0].__setitem__("consistency_to_head", None),
         {"anchor_inconsistent"}),
        ("re-label the anchor under a weaker algorithm",
         lambda b: b["anchors"][0].__setitem__("alg", "ML-DSA-65"),
         {"anchor_signature"}),
        ("swap the pinned anchor key",
         lambda b: b.__setitem__("anchor_pub", b["log_pub"]),
         {"anchor_signature"}),
        ("remove all anchors",
         lambda b: b.__setitem__("anchors", []),
         {"no_anchors"}),
    ]


def _failed_checks(r: dict) -> set[str]:
    """Which checks did not pass, as a set of names."""
    out = set()
    if not r["anchors_present"]:
        out.add("no_anchors")
    if not r["head"]["log_signature_ok"]:
        out.add("head_signature")
    if not r["head"]["quorum_ok"] or r["head"]["witnesses_bad"]:
        out.add("quorum")
    a = r["anchors"]
    if a["bad_signatures"]:
        out.add("anchor_signature")
    if a["inconsistent"]:
        out.add("anchor_inconsistent")
    if a["rollback"]:
        out.add("rollback")
    for e in r["entries"]:
        if not e["ok"]:
            if not e["certificate_ok"]:
                out.add("certificate_ok")
            if not e["inclusion_ok"]:
                out.add("inclusion_ok")
            if not e["request_signature_ok"]:
                out.add("request_signature_ok")
            if not e["sth_signature_ok"]:
                out.add("sth_signature_ok")
            if not e["chained_to_head"]:
                out.add("chained_to_head")
            if e["witnesses_bad"]:
                out.add("witnesses_bad")
            if len(e["witnesses_ok"]) < e["witness_quorum"]:
                out.add("quorum")
    return out


@pytest.mark.parametrize("name,mutate,expected", _mutations(),
                         ids=[m[0] for m in _mutations()])
def test_forgery_is_rejected(bundle, name, mutate, expected):
    mutate(bundle)
    r = verify_bundle(bundle)
    assert r["ok"] is False, f"{name}: verifier accepted a forgery"
    failed = _failed_checks(r)
    assert failed & expected, (
        f"{name}: expected one of {sorted(expected)} to fail, but only "
        f"{sorted(failed)} failed -- the check meant to catch this is broken")


# Mutations that only the independent verifier can see.
#
# ``logfirst.forensics.evidence`` verifies one entry against *its own* committed
# head. It has no notion of the bundle head those heads chain to, and no notion
# of anchors at all, so it cannot detect a mutation that leaves every entry's own
# head intact. These cases are therefore not expected to agree -- the independent
# verifier is strictly stronger here, and that is a property of the design, not a
# divergence.
#
# This list is asserted to be exactly the set where the two disagree, so if
# either verifier changes which claims it checks, the test says so instead of
# silently widening the gap.
BUNDLED_VERIFIER_BLIND_SPOTS = {
    # The head, and each entry's chain to it: per-entry verification stops at
    # the entry's own head.
    "corrupt the chain proof to the head",
    "strip the chain proof to the head",
    "corrupt the head's own signature",
    "strip the head's witness co-signatures",
    "rewrite the head's root",
    # Externalized roots: no anchor logic exists in the bundled verifier.
    "corrupt the anchor's signature",
    "rewrite an externalized root",
    "corrupt the anchor's consistency proof",
    "strip the anchor's consistency proof",
    "re-label the anchor under a weaker algorithm",
    "swap the pinned anchor key",
    "remove all anchors",
}


@pytest.mark.parametrize("name,mutate,expected", _mutations(),
                         ids=[m[0] for m in _mutations()])
def test_the_two_verifiers_agree_where_they_claim_the_same_thing(bundle, name,
                                                                mutate, expected):
    """No field-level disagreement on the checks both implementations perform.

    Where the independent verifier rejects something the package verifier
    accepts, the case must be one of the known blind spots -- otherwise one of
    the two is wrong about a concrete forgery, and the disagreement is itself the
    finding.
    """
    mutate(bundle)
    mine = verify_bundle(bundle)
    theirs = selfcheck(bundle)

    disagree = [
        (a["index"], f)
        for a, b in zip(mine["entries"], theirs["entries"])
        if b["verified"]
        for f in ("certificate_ok", "request_signature_ok", "inclusion_ok",
                  "sth_signature_ok")
        if a[f] is False
    ]
    if theirs["ok"]:
        assert name in BUNDLED_VERIFIER_BLIND_SPOTS, (
            f"{name}: the bundled verifier accepted a forgery the independent "
            f"verifier rejected (fields: {disagree}), and this is not one of "
            "the cases it is known to be blind to")
    else:
        # Both rejected: they must have rejected for the same reasons.
        assert not disagree, f"{name}: field-level disagreement {disagree}"


def test_chain_only_blind_spots_are_real(bundle):
    """The blind-spot list must not be wishful thinking.

    Each named case is checked to actually be blind to the package verifier, so
    the exemption cannot be used to paper over a case the two really do disagree
    about. And the list must not be *incomplete* either: every mutation the
    bundled verifier accepts has to be named here.
    """
    for name, mutate, _ in _mutations():
        b = copy.deepcopy(bundle)
        mutate(b)
        blind = selfcheck(b)["ok"] is True
        if name in BUNDLED_VERIFIER_BLIND_SPOTS:
            assert blind, (
                f"{name} is listed as a blind spot for the bundled verifier, but "
                "it in fact detects it -- the list is out of date")
            assert verify_bundle(b)["ok"] is False, (
                f"{name} is a blind spot for the bundled verifier, so the "
                "independent verifier must catch it -- otherwise nothing does")
        else:
            assert not blind, (
                f"{name} is not listed as a blind spot, but the bundled "
                "verifier accepts it -- add it to the list or fix the check")


def test_removing_the_head_is_a_malformed_bundle_not_a_pass(bundle):
    """A missing head must not be treated as 'skip the chain check'.

    If the field were optional, stripping it would be the cheapest way to make a
    forked entry verify: the chain proof is what connects an entry to a
    witnessed tree, so its absence has to be an error rather than a pass.
    """
    bundle.pop("head")
    with pytest.raises(BundleError):
        verify_bundle(bundle)


def test_unknown_bundle_version_is_refused(bundle):
    bundle["version"] = 99
    with pytest.raises(BundleError):
        verify_bundle(bundle)


def test_empty_entry_list_is_refused(bundle):
    bundle["entries"] = []
    with pytest.raises(BundleError):
        verify_bundle(bundle)


# --------------------------------------------------------------------------
# The quorum boundary
# --------------------------------------------------------------------------

def test_a_quorum_of_two_of_three_is_genuinely_enough(bundle):
    """Stripping one of three co-signatures must still verify at quorum 2.

    Two independent witnesses did attest, so refusing this would be a false
    negative -- and a false negative is not a safe failure mode here: it teaches
    operators to ignore the tool.
    """
    for e in bundle["entries"]:
        e["sth"]["witness_sigs"].pop("w3", None)
    bundle["head"]["witness_sigs"].pop("w3", None)
    r = verify_bundle(bundle)
    assert r["ok"] is True
    for e in r["entries"]:
        assert e["witnesses_missing"] == ["w3"]
        assert not e["witnesses_bad"]


def test_dropping_below_the_quorum_fails(bundle):
    for e in bundle["entries"]:
        e["sth"]["witness_sigs"].pop("w2", None)
        e["sth"]["witness_sigs"].pop("w3", None)
    bundle["head"]["witness_sigs"].pop("w2", None)
    bundle["head"]["witness_sigs"].pop("w3", None)
    r = verify_bundle(bundle)
    assert r["ok"] is False
    assert not r["head"]["quorum_ok"]


# --------------------------------------------------------------------------
# The weak-claim verdict
# --------------------------------------------------------------------------

def test_entries_without_any_anchor_report_a_weaker_result(bundle):
    """No anchor is a gap in the evidence, not a forgery and not a pass.

    The verdict must be distinguishable from both, because the two mistakes are
    opposite: treating it as verified hides an uncaught rewrite, and treating it
    as a forgery discredits an intact bundle.
    """
    bundle["anchors"] = []
    r = verify_bundle(bundle)
    assert r["entries_ok"] is True, "the entries themselves are sound"
    assert r["anchors_present"] is False
    assert r["anchored"] is False
    assert r["ok"] is False


def test_a_failed_anchor_is_not_the_same_as_a_missing_one(bundle):
    """An anchor that was offered and failed is a finding, not a gap.

    Conflating the two would let a corrupted anchor be read as 'history not
    checked' -- which sounds routine -- instead of 'an externalized root
    contradicts this ledger'.
    """
    bundle["anchors"][0]["root_hash"] = "ff" * 32
    r = verify_bundle(bundle)
    assert r["anchors_present"] is True
    assert r["anchored"] is False
    assert r["anchors"]["inconsistent"], "the contradiction must be reported"


def test_rollback_against_a_later_anchor_is_detected(tmp_path):
    """Being shown an old view of the log is its own finding.

    Modelled properly: build a bundle, let the ledger grow, externalize a root at
    the new size, and then verify the *old* bundle. Its head is behind a root
    that has already left the building, so no consistency proof in that direction
    can exist -- which is what distinguishes a rollback from an inconsistency.

    This needs its own ledger rather than the module fixture, because it depends
    on the tree growing after the bundle was taken.
    """
    from logfirst.crypto import ca as ca_mod

    witnesses = make_witnesses(tmp_path, 3)
    log = LedgerLog.open(str(tmp_path / "ledger.db"),
                         WitnessQuorum(list(witnesses), min_witnesses=2))
    ca = ca_mod.CA.create()
    certs = {}
    for i in range(4):
        rid = f"r{i}"
        cert, secrets = ca_mod.enroll_recipient(ca, rid)
        certs[rid] = cert.__dict__
        log.gated_append_for_decryption(
            make_request(rid, f"DOC-{i:04d}",
                         sig_sec=bytes.fromhex(secrets["sig_sec"])).leaf_bytes(),
            "127.0.0.1")

    exporter = BundleExporter(
        log_pub=log.log_pub,
        witness_pubs={w.witness_id: w.signer.sig_pub for w in witnesses},
        recipient_certs=certs, witness_quorum=2,
        anchor_pub=Anchorer.open(str(tmp_path / "anchors.jsonl")).anchor_pub,
        ca_pub=ca.sig_pub)
    old_bundle = exporter.bundle(log, [0, 1], [])

    # The ledger grows, and a root at the new size is externalized.
    for i in range(4, 6):
        rid = f"r{i}"
        cert, secrets = ca_mod.enroll_recipient(ca, rid)
        certs[rid] = cert.__dict__
        log.gated_append_for_decryption(
            make_request(rid, f"DOC-{i:04d}",
                         sig_sec=bytes.fromhex(secrets["sig_sec"])).leaf_bytes(),
            "127.0.0.1")
    anchorer = Anchorer.open(str(tmp_path / "anchors.jsonl"))
    later = anchorer.anchor(
        log.tree_size(),
        merkle.root_from_hashes(log.leaf_hashes()).hex())

    # Serve the stale bundle, but with the newer anchor attached -- as an
    # operator would who wanted the anchor's credibility without its content.
    stale = copy.deepcopy(old_bundle)
    stale["anchors"] = [later]
    r = verify_bundle(stale)
    assert r["anchors"]["rollback"] is True
    assert r["anchors"]["inconsistent"] == [], (
        "a rollback must be reported as a rollback, not as an inconsistency: "
        "there is no proof in this direction to check")
    assert r["ok"] is False
    assert r["entries_ok"] is True, "the entries themselves are untouched"


# --------------------------------------------------------------------------
# The exporter's own guards
# --------------------------------------------------------------------------

def test_exporter_refuses_an_index_without_a_witnessed_head(env, tmp_path):
    """A ledger whose head row was deleted must not export a substitute head.

    Exporting against the current head instead would produce a bundle that
    verifies a claim no witness ever attested to -- the exact failure the
    exporter exists to prevent.
    """
    log = env["log"]
    log.conn.execute("DELETE FROM sth WHERE tree_size = ?", (ANCHOR_SIZE,))
    log.conn.commit()
    with pytest.raises(ExportError, match="no witnessed head"):
        env["exporter"].entry(log, ANCHOR_SIZE - 1, log.tree_size())


def test_exporter_refuses_an_out_of_range_index(env):
    log = env["log"]
    with pytest.raises(ExportError):
        env["exporter"].bundle(log, [log.tree_size()])


def test_exporter_refuses_an_unknown_recipient(env):
    """Without the certificate the bundle could not bind a key to an identity.

    Emitting it anyway would produce a bundle that fails at the certificate
    check, which reads as tampering rather than as a missing input.
    """
    log = env["log"]
    exporter = BundleExporter(
        log_pub=log.log_pub, witness_pubs={}, recipient_certs={},
        witness_quorum=2, anchor_pub=None, ca_pub=env["ca"].sig_pub)
    with pytest.raises(ExportError, match="no certificate for recipient"):
        exporter.entry(log, 0, log.tree_size())


def test_a_bundle_without_a_ca_key_is_refused(bundle):
    """The CA key is required, not optional.

    If it were optional, omitting it would downgrade the check from "this
    recipient's certified key signed" to "some key signed" -- silently, while
    still reporting success.
    """
    bundle.pop("ca_pub")
    with pytest.raises(BundleError, match="ca_pub"):
        verify_bundle(bundle)


def test_bundle_round_trips_through_json(bundle, tmp_path):
    """Serialisation must not change any bytes that are hashed or signed."""
    p = tmp_path / "b.json"
    p.write_text(json.dumps(bundle))
    assert verify_bundle(json.loads(p.read_text()))["ok"] is True
