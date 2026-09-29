"""The leak-check pipeline, end to end, on really-marked copies.

Every other test file checks one layer. This one runs the pipeline the build
specification actually asks for, on artefacts produced by real code:

    a corpus document
      -> a real signed decryption request for a real CA-issued identity
      -> a real ledger append with real witness co-signatures
      -> a copy marked with the seed bound to that committed entry
      -> handed to the investigator as leaked text
      -> identification, alignment, extraction, RS decode, Tardos trace
      -> independent verification of the entry the watermark points at

The point of running it whole is that the layers were designed against each
other's assumptions, and only an end-to-end run tests the junctions: that
``mark_copy``'s layout is the one ``plan_for_document`` gives the investigator,
that the seed the investigator recomputes from the committed leaf is the one the
marker used, and that the Tardos code the investigator scores against is the one
the copies were written from. Each of those is a place where two modules can
agree with themselves and disagree with each other.

What is asserted about the *output* is as important as the attribution itself,
and follows the honesty constraints in the specification:

* document-match confidence and watermark-recovery confidence are separate
  fields and are asserted to be separate,
* the fallback path -- "these recipients decrypted this document", with no
  watermark -- is asserted to be labelled as the weaker evidence it is, and to
  never appear as an attribution,
* a candidate is never returned without a score, and the Tardos guarantee level
  is carried alongside every candidate list,
* every result carries the caveat that this identifies a key, a device and a
  session, not a person.
"""

from __future__ import annotations

import json
import math
import random

import numpy as np
import pytest

from logfirst.crypto import ca as ca_mod
from logfirst.crypto import pqc
from logfirst.forensics.investigate import (
    ATTRIBUTION_CAVEAT, STATUS_ATTRIBUTED, STATUS_COLLUSION, STATUS_EMPTY,
    STATUS_NO_WATERMARK, STATUS_SINGLE_MARK, STATUS_UNIDENTIFIED,
    STATUS_UNVERIFIED, Investigator,
)
from logfirst.ledger.log import LedgerLog
from logfirst.ledger.witnesses import WitnessQuorum
from logfirst.models import DecryptionRequest
from logfirst.watermark import linguistic, payload
from logfirst.watermark.tardos import TardosCode, code_length

from tests.conftest import make_witnesses

RECIPIENTS = ["alice", "bob", "carol", "dave"]
USERS = 4
COLLUDERS = 2
EPS = 1e-3
# Long enough that the pointer gets its full repetition budget and a Tardos
# region clears MIN_TARDOS. See README "Watermark capacity" for the ratio.
TARGET_WORDS = 2000


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """A running ledger, four enrolled identities, and a corpus.

    Module-scoped because ML-DSA keygen and the corpus generator are the slow
    parts, and none of the tests below mutate any of it.
    """
    from logfirst.data import corpus

    root = tmp_path_factory.mktemp("leakcheck")
    witnesses = make_witnesses(root, 3)
    log = LedgerLog.open(str(root / "ledger.db"),
                         WitnessQuorum(witnesses, min_witnesses=2))

    ca = ca_mod.CA.create()
    certs, secrets = {}, {}
    for rid in RECIPIENTS:
        cert, secret = ca_mod.enroll_recipient(ca, rid)
        certs[rid] = cert
        secrets[rid] = secret

    docs = corpus.make_document_set(3, seed=5, target_words=TARGET_WORDS)
    return {
        "root": root, "witnesses": witnesses, "log": log, "ca": ca,
        "certs": certs, "secrets": secrets, "docs": docs,
    }


def open_document(world, doc: dict, recipient: str) -> dict:
    """One open: a signed request, a real append, and the seed that came back.

    This mirrors what the authority does -- the request is signed by the
    recipient's own ML-DSA key over the same bytes the ledger commits -- without
    standing up the HTTP service, which ``test_authority_http.py`` covers.
    """
    eph_pub, _ = pqc.kem_keypair(pqc.KEM)
    dr = DecryptionRequest(
        doc_id=doc["doc_id"], recipient_id=recipient,
        nonce=f"{len(world['docs'])}{recipient}".ljust(16, "0")[:16],
        timestamp="2026-02-01T00:00:00+00:00", device_fp="ab" * 32,
        ephemeral_kem_pub=eph_pub.hex())
    dr.sig = pqc.sign(bytes.fromhex(world["secrets"][recipient]["sig_sec"]),
                      dr.tbs(), pqc.SIG).hex()
    return world["log"].gated_append_for_decryption(dr.leaf_bytes(), "198.51.100.9")


def mark(world, doc: dict, opened: dict, user_index: int, code: TardosCode
         ) -> str:
    """The copy the recipient keeps: the document with this session's mark.

    Mirrors ``ClientNode.mark_copy`` exactly, and the mirroring matters: the
    payload is the pointer *plus* this user's Tardos codeword, at the layout
    ``plan_for_document`` gives both sides. Marking with the pointer alone would
    put the payload positions at a different modulus from the ones the
    investigator reads, and the mark would be unreadable -- which is how this
    helper was caught being wrong.
    """
    slots = linguistic.slot_count(doc["text"])
    plan = payload.plan_for_document(slots, USERS, COLLUDERS, EPS)
    assert plan["ok"], plan["reason"]
    tardos_bits = (code.codeword(user_index, plan["tardos_bits"])
                   if plan["tardos_bits"] else None)
    bits = payload.build_payload(opened["index"], tardos_bits)
    assert bits.size == plan["total_bits"]
    marked, _ = linguistic.embed(doc["text"], bits,
                                 bytes.fromhex(opened["watermark_seed"]),
                                 masked_bits=plan["pointer_bits"])
    return marked


@pytest.fixture(scope="module")
def sessions(world):
    """One marked copy per recipient of the first document.

    The Tardos code is built at the *formal* length and the document carries a
    truncated prefix of it, which is the arrangement ``Deployment.tardos`` uses
    in the demo and the one the prefix property in ``TardosCode.generate``
    exists for.
    """
    doc = world["docs"][0]
    plan = payload.plan_for_document(linguistic.slot_count(doc["text"]),
                                     USERS, COLLUDERS, EPS)
    code = TardosCode.generate(USERS, COLLUDERS, EPS,
                               m=code_length(USERS, COLLUDERS, EPS), seed=777)
    out = {}
    for i, rid in enumerate(RECIPIENTS):
        opened = open_document(world, doc, rid)
        out[rid] = {"opened": opened,
                    "marked": mark(world, doc, opened, i, code),
                    "user_index": i}
    return {"doc": doc, "plan": plan, "code": code, "copies": out}


@pytest.fixture(scope="module")
def investigator(world, sessions):
    return Investigator(
        docs=world["docs"], ledger=world["log"], log_pub=world["log"].log_pub,
        witness_pubs={w.witness_id: w.signer.sig_pub for w in world["witnesses"]},
        recipient_pubs={rid: bytes.fromhex(c.sig_pub)
                        for rid, c in world["certs"].items()},
        tardos=sessions["code"], user_order=list(RECIPIENTS),
        witness_quorum=2, max_colluders=COLLUDERS, eps=EPS)


def splice(rng: random.Random, a: str, b: str) -> str:
    """Two recipients compare their copies and mix them.

    This is the realistic attack, not a toy: wherever the two copies carry the
    same word the splicer has no choice and must keep it, and only where they
    differ can they pick. That is exactly the marking assumption Tardos is
    proved against, so building the mixture any other way would be testing a
    stronger adversary than the code claims to resist.
    """
    out = []
    for wa, wb in zip(linguistic._TOKEN.findall(a), linguistic._TOKEN.findall(b)):
        out.append(wa if wa == wb else rng.choice([wa, wb]))
    return " ".join(out)


# ==========================================================================
# The happy path
# ==========================================================================

def test_a_marked_copy_is_traced_to_the_session_that_produced_it(
        world, sessions, investigator):
    """The whole pipeline, on a copy a real recipient would hold."""
    rid = "carol"
    copy = sessions["copies"][rid]

    inv = investigator.investigate(leaked_text=copy["marked"])

    assert inv.status == STATUS_ATTRIBUTED, (inv.status, inv.notes)
    assert inv.watermark_recovered is True
    assert inv.pointer_index == copy["opened"]["index"]
    assert inv.doc_id == sessions["doc"]["doc_id"]

    # The attribution names the right person, with the evidence attached.
    assert inv.candidates, "an attribution with no candidate is not an attribution"
    top = inv.candidates[0]
    assert top.recipient_id == rid
    assert top.source == "ledger-pointer"
    assert top.ledger_index == copy["opened"]["index"]

    # ...and that entry was independently verified, not taken on the server's
    # word.
    assert inv.verification is not None
    assert inv.verification["verified"] is True
    assert inv.verification["request_signature_ok"] is True
    assert inv.verification["inclusion_ok"] is True
    assert inv.verification["sth_signature_ok"] is True
    assert inv.verification["witness_quorum_ok"] is True
    assert inv.verification["witnesses_bad"] == []


def test_every_recipients_copy_traces_to_that_recipient(world, sessions,
                                                        investigator):
    """Not just one lucky copy: the mark really is per-recipient."""
    for rid, copy in sessions["copies"].items():
        inv = investigator.investigate(leaked_text=copy["marked"])
        assert inv.status == STATUS_ATTRIBUTED, (rid, inv.status, inv.notes)
        assert inv.candidates[0].recipient_id == rid, (
            f"{rid}'s copy was attributed to {inv.candidates[0].recipient_id}")


def test_a_fragment_of_a_copy_still_traces(world, sessions, investigator):
    """Leaks are paragraphs, not whole documents.

    The identification stage needs enough text to recognise the document and the
    extraction stage needs enough surviving carrier slots to fill the payload.
    A 60% excerpt is well inside both, and is the realistic case.
    """
    copy = sessions["copies"]["bob"]
    toks = copy["marked"].split()
    fragment = " ".join(toks[:int(len(toks) * 0.6)])

    inv = investigator.investigate(leaked_text=fragment)
    assert inv.status == STATUS_ATTRIBUTED, (inv.status, inv.notes)
    assert inv.candidates[0].recipient_id == "bob"


# ==========================================================================
# Two confidences, reported separately
# ==========================================================================

def test_document_confidence_and_watermark_confidence_are_reported_apart(
        sessions, investigator):
    """The specification's honesty requirement, asserted as a shape.

    "How sure are we this is the right source document" and "how sure are we the
    watermark decoded" are different questions with different failure modes, and
    a single blended number would hide exactly the case an analyst most needs to
    see: a fragment that matches a document strongly and yields no watermark.
    The two fields carry different values here, which is what makes them two
    fields rather than one.
    """
    inv = investigator.investigate(
        leaked_text=sessions["copies"]["alice"]["marked"])
    out = inv.as_dict()

    assert "confidence" in out["document"]
    assert "confidence" in out["watermark"]
    assert out["document"]["confidence"] != out["watermark"]["confidence"]
    assert 0.0 < out["document"]["confidence"] <= 1.0
    assert 0.0 <= out["watermark"]["confidence"] <= 1.0
    # Independent of each other: the document match is a cosine over n-grams and
    # the watermark confidence comes from how many RS symbols needed repair.
    assert out["watermark"]["recovered"] is True
    assert out["document"]["candidates"], "the ranked document list is dropped"


def test_every_result_carries_the_attribution_caveat(investigator):
    """A result that identifies a key must say that it identifies a key.

    This is not documentation, it is a field on every output, because the one
    place it will be read is a report that has been separated from its README.
    """
    for text in ("", "some entirely unrelated paragraph about marine biology"):
        assert investigator.investigate(leaked_text=text).as_dict()["caveat"] \
            == ATTRIBUTION_CAVEAT
    assert "does not establish which person" in ATTRIBUTION_CAVEAT


# ==========================================================================
# The fallback: no watermark, but a truthful ledger list
# ==========================================================================

def test_an_unmarked_copy_falls_back_and_says_so(world, sessions, investigator):
    """An honest failure is still useful evidence, and must be labelled.

    Strip the mark -- a recipient who edits, or a copy that predates marking --
    and the pipeline cannot name a session. What it *can* say is which
    recipients' signatures are on file for this document, each with a timestamp.
    That is a true statement about who decrypted it and says nothing about which
    copy leaked, so it must not be promoted into an attribution.
    """
    inv = investigator.investigate(leaked_text=sessions["doc"]["text"])

    assert inv.status in (STATUS_NO_WATERMARK, STATUS_COLLUSION), inv.status
    assert inv.watermark_recovered is False
    assert inv.watermark_confidence == 0.0
    for cand in inv.candidates:
        assert cand.source != "ledger-pointer", (
            "a fallback result produced a ledger-pointer candidate, which is "
            "an attribution the watermark did not support")

    # The ledger sessions are listed, and the note says what they are.
    assert inv.ledger_sessions, "the fallback did not list the ledger sessions"
    assert {s["recipient_id"] for s in inv.ledger_sessions} == set(RECIPIENTS)
    assert any("fallback" in n or "did not decode" in n for n in inv.notes), \
        inv.notes


def test_the_fallback_lists_every_session_not_the_best_one(world, investigator):
    """The fallback is a list, and completeness is the point.

    Narrowing it to one row would be the pipeline making a choice the watermark
    did not support -- the exact failure the fallback's labelling exists to
    prevent.
    """
    doc = world["docs"][1]
    for rid in ("alice", "dave"):
        open_document(world, doc, rid)
    inv = investigator.investigate(leaked_text=doc["text"])

    assert inv.watermark_recovered is False
    listed = {(s["recipient_id"], s["ledger_index"]) for s in inv.ledger_sessions}
    assert len(listed) == 2, listed
    # Every listed row is a real verified-shaped entry with its own index.
    for s in inv.ledger_sessions:
        assert isinstance(s["ledger_index"], int)
        assert s["timestamp"]


# ==========================================================================
# Collusion
# ==========================================================================

def test_a_spliced_copy_reports_collusion_and_ranks_by_tardos(
        world, sessions, investigator):
    """The attack the Tardos layer exists for.

    Two recipients mix their copies. The pointer is usually destroyed -- no
    single session's seed describes the result -- but the Tardos region was
    written unmasked precisely so that it stays a linear combination of the
    colluders' codewords.

    A splice does not *always* destroy the pointer. The copies are marked under
    seeds derived from real ML-DSA signatures, which are randomised, so some
    runs leave enough of the pointer region intact to decode and name one of the
    two colluders. That is a better outcome than a bare ranking, not a worse one,
    and the test asserts the invariant that holds either way: an innocent is
    never named, and whatever is reported carries a score and its guarantee
    level.
    """
    rng = random.Random(4)
    mixed = splice(rng, sessions["copies"]["alice"]["marked"],
                   sessions["copies"]["bob"]["marked"])
    assert mixed != sessions["copies"]["alice"]["marked"]

    inv = investigator.investigate(leaked_text=mixed)

    assert inv.candidates, "the trace produced nothing at all to rank"
    assert inv.candidates[0].recipient_id in ("alice", "bob"), (
        f"the top suspect is {inv.candidates[0].recipient_id}, who is not a "
        "colluder")
    # ``single-mark`` is included because a splice can resolve almost entirely
    # one way: it differs from either copy only where the two codewords differ,
    # and the arcsine bias puts most positions where two users share a bit. That
    # case is reported as one mark rather than a mixture, deliberately, and the
    # invariant below -- the status and the watermark flag must agree -- is what
    # this test is actually guarding.
    assert inv.status in (STATUS_ATTRIBUTED, STATUS_COLLUSION,
                          STATUS_SINGLE_MARK, STATUS_NO_WATERMARK), \
        (inv.status, inv.notes)

    if inv.status == STATUS_ATTRIBUTED:
        # The pointer survived the mix and named a real colluder's session.
        assert inv.watermark_recovered is True
        assert inv.pointer_index in (sessions["copies"]["alice"]["opened"]["index"],
                                     sessions["copies"]["bob"]["opened"]["index"])
    else:
        assert inv.watermark_recovered is False, (
            "a spliced copy decoded a single session's pointer but did not "
            "report it, so the status and the watermark flag disagree")

    # Ranked, with scores, and labelled as ranking rather than accusation.
    for cand in inv.candidates:
        assert math.isfinite(cand.tardos_score)
        assert math.isfinite(cand.tardos_threshold)
        assert cand.tardos_threshold > 0.0
    assert inv.guarantee in ("ranking-only", "formal", "none")
    assert any("rank" in n.lower() or "splice" in n.lower() or "Tardos" in n
               for n in inv.notes), inv.notes


def test_a_spliced_copy_never_names_a_single_suspect_without_a_score(
        world, sessions, investigator):
    """The specification's 'never a bare accusation' rule, over many splices.

    Across repeated splices of the same pair, every outcome the pipeline can
    produce must be backed by evidence: either a pointer that decoded to a real
    colluder's verified ledger entry, or Tardos-ranked candidates carrying their
    scores. It is allowed to rank an *innocent* first sometimes -- at these code
    lengths the formal bound does not apply and the pipeline says so in as many
    words -- but it is not allowed to emit a name with nothing behind it, and it
    is never allowed to attribute to someone who is not a colluder.

    The loop matters because the outcome genuinely varies run to run: the seeds
    come from randomised ML-DSA signatures, so whether a given splice leaves its
    pointer decodable is not fixed. A single trial would assert whichever
    branch happened to come up.
    """
    named_wrong = 0
    saw_attributed = saw_ranked = False
    for trial in range(8):
        rng = random.Random(100 + trial)
        mixed = splice(rng, sessions["copies"]["carol"]["marked"],
                       sessions["copies"]["dave"]["marked"])
        inv = investigator.investigate(leaked_text=mixed)
        assert inv.status in (STATUS_ATTRIBUTED, STATUS_COLLUSION,
                              STATUS_SINGLE_MARK, STATUS_NO_WATERMARK), \
            (inv.status, inv.notes)

        if inv.status == STATUS_ATTRIBUTED:
            saw_attributed = True
            # The hard rule: an attribution names a verified ledger entry, and a
            # splice of two colluders' copies can only ever point at one of
            # those two. Naming anyone else would be a false attribution.
            assert inv.watermark_recovered is True
            assert inv.verification is not None
            assert inv.verification["verified"] is True
            assert inv.candidates[0].recipient_id in ("carol", "dave"), (
                f"a splice of carol's and dave's copies was attributed to "
                f"{inv.candidates[0].recipient_id}")
            assert inv.pointer_index in (
                sessions["copies"]["carol"]["opened"]["index"],
                sessions["copies"]["dave"]["opened"]["index"])
        else:
            saw_ranked = True
            assert inv.watermark_recovered is False
            assert inv.candidates, (
                "no watermark and no Tardos candidates: nothing was reported "
                "at all, which is a silent failure rather than a refusal")

        for cand in inv.candidates:
            assert cand.source in ("tardos-trace", "ledger-pointer")
            # A score is *not* required to be positive: an innocent's symmetric
            # Tardos score is centred on zero, and roughly half of them come out
            # below it. Requiring a non-negative ratio here would be requiring
            # the trace to be biased against everyone it looks at, which is the
            # opposite of what the score means. What must hold is that the score
            # is a real finite number, so that whatever ranking it produces is
            # backed by something.
            assert math.isfinite(cand.tardos_score)
            assert math.isfinite(cand.score_ratio)
            assert math.isfinite(cand.tardos_threshold)
            assert cand.tardos_threshold > 0.0
            assert cand.score_ratio == pytest.approx(
                cand.tardos_score / cand.tardos_threshold, rel=1e-6)
            assert cand.crosses_threshold == (cand.tardos_score
                                              > cand.tardos_threshold)
            assert isinstance(cand.crosses_threshold, bool)
        if (inv.status != STATUS_ATTRIBUTED and inv.candidates
                and inv.candidates[0].recipient_id not in ("carol", "dave")):
            named_wrong += 1
    # Ranking is good at this length but not guaranteed, which is the whole
    # reason for the ranking-only label. If this ever hit 0 the label would be
    # understating the trace; if it hit 8 the ranking would be worthless. Only
    # the ranked outcomes count: an attribution has already been asserted above
    # to name a colluder.
    assert named_wrong < 8, (
        "every splice ranked a non-colluder first, so the trace is not "
        "correlating with the colluders at all")
    assert saw_attributed or saw_ranked


# ==========================================================================
# Refusals
# ==========================================================================

def test_text_from_outside_the_corpus_is_reported_as_unidentified(investigator):
    """The floor, end to end: wrong text must not become an attribution.

    This is the path the old ``MIN_IDENTIFY_SCORE`` of 0.05 could not reach --
    ordinary prose scored above it, so the pipeline would have proceeded to
    extract bits from the least-bad document match and reported whatever came
    out. ``tests/test_identify.py`` calibrates the constant; this asserts the
    pipeline honours it.
    """
    inv = investigator.investigate(leaked_text=(
        "Shall I compare thee to a summer's day? Thou art more lovely and more "
        "temperate. Rough winds do shake the darling buds of May, and summer's "
        "lease hath all too short a date. Sometime too hot the eye of heaven "
        "shines, and often is his gold complexion dimmed."))
    assert inv.status == STATUS_UNIDENTIFIED, (inv.status, inv.notes)
    assert inv.candidates == []
    assert inv.watermark_recovered is False


def test_empty_input_is_refused_rather_than_analysed(investigator):
    for kwargs in ({"leaked_text": ""}, {"leaked_text": "   \n  "}):
        inv = investigator.investigate(**kwargs)
        assert inv.status == STATUS_EMPTY
        assert inv.candidates == []


def test_an_unreadable_image_is_refused_with_a_reason(investigator):
    inv = investigator.investigate(image_bytes=b"this is not a png")
    assert inv.status == STATUS_EMPTY
    assert any("image" in n for n in inv.notes), inv.notes


def test_a_tampered_head_is_caught_by_the_witnesses_not_the_inclusion_proof(
        world, sessions, investigator):
    """The check that makes the whole chain non-repudiable rather than recorded.

    A watermark names a ledger index. The mark on the leaked copy is untouched
    here -- so the pointer still decodes to the right entry and the inclusion
    proof still folds correctly, because the leaf really is in the tree. What has
    been tampered with is the *head*: one witness's co-signature over the tree of
    that size has been corrupted.

    That is precisely the case a server-side-only check would miss. Verifying the
    leaf against the tree the server hands you proves nothing when the server
    chose the head. It is the witnesses -- separate processes holding separate
    keys -- that make the head itself checkable, and their disagreement is what
    has to surface here.
    """
    victim = "dave"
    copy = sessions["copies"][victim]
    idx = copy["opened"]["index"]
    size = idx + 1                       # the tree this entry was committed into

    row = world["log"].conn.execute(
        "SELECT witness_sigs FROM sth WHERE tree_size=?", (size,)).fetchone()
    original_sigs = row["witness_sigs"]
    sigs = json.loads(original_sigs)
    good_witness = sorted(sigs)[0]
    # Corrupt the signature, not the witness list: a witness that is present but
    # does not verify means the head was altered after signing, which is a
    # different and graver report than a witness that was merely absent.
    sigs[good_witness] = "00" * len(sigs[good_witness])
    world["log"].conn.execute("UPDATE sth SET witness_sigs=? WHERE tree_size=?",
                              (json.dumps(sigs), size))
    world["log"].conn.commit()
    try:
        inv = investigator.investigate(leaked_text=copy["marked"])

        # The pointer still decodes -- the leaf was not touched -- so this is
        # genuinely the verification stage refusing, not extraction failing.
        assert inv.watermark_recovered is True, (inv.status, inv.notes)
        assert inv.pointer_index == idx
        assert inv.status == STATUS_UNVERIFIED, (inv.status, inv.notes)
        assert inv.candidates == [], (
            "an attribution was reported from an entry that failed verification")
        assert inv.verification is not None
        assert inv.verification["verified"] is False
        # The specific check that failed, so the report is diagnostic rather
        # than a bare refusal.
        assert good_witness in inv.verification["witnesses_bad"]
        assert inv.verification["inclusion_ok"] is True, (
            "the inclusion proof should still pass here -- the leaf is genuine, "
            "only the head was tampered with; if this failed the test would not "
            "be isolating the witness check")
        assert any("FAILED verification" in n for n in inv.notes), inv.notes
    finally:
        world["log"].conn.execute("UPDATE sth SET witness_sigs=? WHERE tree_size=?",
                                  (original_sigs, size))
        world["log"].conn.commit()


def test_a_tampered_leaf_makes_the_pointer_undecodable_rather_than_misattributing(
        world, sessions, investigator):
    """The other tamper path, which lands somewhere different and must be named.

    Altering the *committed leaf* does not produce a failed verification check,
    because the watermark seed is derived from the leaf's own hash: change the
    leaf and the seed the investigator recomputes is no longer the one the copy
    was marked under, so the pointer does not decode at all.

    That is the right outcome -- a pointer that cannot be decoded names nobody --
    but it is a *different* outcome from a failed verification, and conflating
    the two would mean a report claiming "the entry failed verification" when
    verification never ran. What must hold either way is the rule this whole file
    exists to check: no attribution is produced.

    The copy is one recipient's own, so the Tardos channel still sees one
    elevated user. That is reported as a ranked candidate carrying its score and
    explicitly *not* as a collusion: one person's copy is not a conspiracy, and
    calling it one would be a false statement about them. The candidate is
    evidence of who the copy belonged to, which is not the same as an attribution
    -- no ledger entry was verified, and the status must not say one was.
    """
    victim = "dave"
    copy = sessions["copies"][victim]
    idx = copy["opened"]["index"]

    original = world["log"].get_leaf(idx)
    tampered = original.replace(b'"device_fp":"ab', b'"device_fp":"ff', 1)
    assert tampered != original, "the tamper did not change the leaf"
    world["log"].conn.execute("UPDATE leaves SET leaf_data=? WHERE idx=?",
                              (tampered, idx))
    world["log"].conn.commit()
    try:
        inv = investigator.investigate(leaked_text=copy["marked"])
        # ``single-mark``, not ``no-watermark``: the mark is still there and one
        # candidate is ranked by it. What the tamper destroyed is the *seed* the
        # pointer would have been read under, so the entry cannot be named -- but
        # saying "no watermark" would tell a caller reading only the status the
        # opposite of what the pipeline found.
        assert inv.status == STATUS_SINGLE_MARK, (inv.status, inv.notes)
        assert inv.status != STATUS_NO_WATERMARK, (
            "a copy carrying a readable single mark must not be reported as "
            "carrying none")
        assert inv.status != STATUS_ATTRIBUTED
        assert inv.pointer_index is None
        assert inv.watermark_recovered is False
        assert inv.verification is None, (
            "verification cannot have run: no pointer decoded, so no entry was "
            "ever nominated for checking")
        # One person's mark, reported as such rather than as a collusion.
        assert any("single mark" in n or "accusation threshold" in n
                   for n in inv.notes), inv.notes
        assert inv.candidates, (
            "the copy carries a readable Tardos mark, so the recipient it "
            "belongs to should be ranked rather than discarded")
        assert max(c.tardos_score for c in inv.candidates) > \
            inv.candidates[0].tardos_threshold
    finally:
        world["log"].conn.execute("UPDATE leaves SET leaf_data=? WHERE idx=?",
                                  (original, idx))
        world["log"].conn.commit()
        world["log"]._reload_cache()


# ==========================================================================
# The output contract
# ==========================================================================

def test_every_result_serialises_completely(sessions, investigator):
    """The API and the UI read these dicts, so every field must be jsonable."""
    import json

    for text in (sessions["copies"]["alice"]["marked"], "", "unrelated prose"):
        out = investigator.investigate(leaked_text=text).as_dict()
        json.dumps(out)                     # raises if anything is not
        for key in ("status", "document", "watermark", "candidates",
                    "verification", "ledger_sessions", "notes", "caveat"):
            assert key in out, f"{key} missing from the result"
        for key in ("recovered", "confidence", "ledger_index",
                    "tardos_guarantee"):
            assert key in out["watermark"]


def test_a_candidate_is_never_returned_without_its_score(sessions,
                                                         investigator):
    """No bare accusation, checked on every candidate the pipeline can emit."""
    rng = random.Random(9)
    inputs = [
        sessions["copies"]["alice"]["marked"],
        sessions["doc"]["text"],
        splice(rng, sessions["copies"]["alice"]["marked"],
               sessions["copies"]["bob"]["marked"]),
    ]
    for text in inputs:
        inv = investigator.investigate(leaked_text=text)
        for cand in inv.candidates:
            assert cand.recipient_id
            assert isinstance(cand.crosses_threshold, bool)
            assert cand.source in ("ledger-pointer", "tardos-trace")
            d = cand.as_dict()
            assert "tardos_score" in d and "tardos_threshold" in d
            assert "score_ratio" in d


def test_the_tardos_guarantee_is_carried_into_the_result(sessions, investigator):
    """A candidate list must say how much the Tardos code behind it proves.

    At the code lengths a real document supports the answer is 'ranking only',
    and a UI that showed the list without that word would be presenting a lead
    as a finding.
    """
    inv = investigator.investigate(leaked_text=sessions["copies"]["bob"]["marked"])
    assert inv.tardos_positions > 0, (
        "no Tardos positions were planned for this document, so the collusion "
        "channel is dead and the trace can only ever be pointer-based")
    assert inv.tardos_required > inv.tardos_positions
    assert inv.guarantee == "ranking-only"
    assert any("RANKED" in n or "ranking" in n.lower() for n in inv.notes), \
        "the ranking-only caveat is missing from the notes"
