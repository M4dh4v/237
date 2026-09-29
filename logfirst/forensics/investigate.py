"""The leak-check pipeline.

Input is a leaked artefact -- a screenshot or a pasted block of text. Output is a
ranked set of candidates with the evidence for each, or an explicit statement
that nothing could be recovered. The pipeline is:

    OCR (if image)
      -> identify the source document
      -> align the leaked text against the canonical original
      -> recover soft bits from the carrier slots
      -> RS-decode the ledger pointer; Tardos-trace the collusion code
      -> verify the ledger entry independently (signature, inclusion, witnesses)
      -> rank and report

The seed problem, and why this pipeline is shaped the way it is
---------------------------------------------------------------
The watermark seed is derived from the ledger entry of the specific open, so
that two opens of the same document carry different marks. That makes the seed
*unknowable* to the investigator until the pointer has been decoded -- and
decoding the pointer needs the seed. The circularity is broken by searching:
the ledger tells us every session in which this document was decrypted, each
session yields a candidate seed, and each candidate seed is tried in turn.

The search is not a weakness, because it is *self-validating*. A wrong seed
produces bits that are effectively random, and random bits do not RS-decode to a
pointer that points back at the very entry the seed came from. A hit therefore
requires that the seed derived from entry *N* recovers a watermark naming entry
*N* -- which is exactly the consistency the attribution claim needs, and it is
checked against the ledger entry itself rather than assumed.

The Tardos region needs no seed at all (see ``linguistic.embed``), so it is read
once and independently of the pointer. That independence is the point: when a
collusion has spliced two copies, the pointer is expected to be destroyed and
Tardos is the part that still works.

Three properties of the output matter more than the ranking itself, and all three
are structural here rather than a matter of the caller remembering to be careful.

**Two confidences, reported separately.** How sure we are that this is the right
*source document* and how sure we are that the *watermark decoded* are different
questions with different failure modes. A fragment can match a document at 0.94
cosine while the watermark recovers nothing (the leaker edited the text, or the
OCR was too poor). Reporting one blended number would hide exactly the case an
analyst most needs to see, so :class:`Investigation` carries them apart and the
front end shows both.

**The fallback says what it is.** When the watermark does not decode there is
still something true and useful to say -- *these* recipients decrypted this
document, at *these* times, each with a signature on file -- and the pipeline
says it, labelled as the weaker corroborating evidence it is. What it must never
do is quietly promote that list into an accusation. The distinction is carried in
``status`` and in ``watermark_recovered``.

**No bare accusation.** A candidate is only ever produced with a score, and
whether the Tardos bound actually applies at this code length is reported
alongside it (see :func:`payload.plan`). At the code lengths a normal document
supports, tracing reliably *ranks* colluders but does not cross the formal
accusation threshold; the pipeline reports that rather than presenting a ranked
list as if it were a proof.

The honesty constraint from the build specification applies to everything this
module emits and is repeated in :data:`ATTRIBUTION_CAVEAT`: this establishes
which key, device and session decrypted the document and whose signature
authorised it. It does not establish which human being was holding the keyboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..crypto.kdf import watermark_seed
from ..ledger import merkle
from ..watermark import linguistic, payload
from ..watermark import tardos as tardos_mod
from ..watermark.tardos import TardosCode
from . import align, evidence
from .bundle import _commit_size

# Repeated verbatim into every result the pipeline produces. Kept as one
# constant so it cannot drift between the API, the UI and the report.
ATTRIBUTION_CAVEAT = (
    "Attribution identifies the key, device and session that decrypted this "
    "document, and the signature that authorised the decryption. It does not "
    "establish which person was operating that key. If a key was shared, "
    "copied or stolen, this evidence points at the key holder of record."
)

STATUS_ATTRIBUTED = "attributed"
STATUS_UNVERIFIED = "attribution-unverified"
STATUS_COLLUSION = "collusion-suspected"
# One person's mark cleared the accusation threshold and nobody else came near
# it, but the pointer did not decode, so no session can be named. This is
# deliberately *not* ``no-watermark``: the pipeline did find a mark, belonging to
# one candidate it can rank, and a consumer keying off the status string would
# read "no watermark" and conclude the opposite of what was found. The three
# Tardos verdicts get three statuses so the machine-readable field and the note
# beside it cannot disagree.
STATUS_SINGLE_MARK = "single-mark"
STATUS_NO_WATERMARK = "no-watermark"
STATUS_UNIDENTIFIED = "unidentified"
STATUS_EMPTY = "empty-input"


@dataclass
class Candidate:
    """One ranked suspect, with the evidence that put them there."""

    recipient_id: str
    user_index: int
    tardos_score: float
    tardos_threshold: float
    score_ratio: float
    crosses_threshold: bool
    source: str            # "ledger-pointer" | "tardos-trace"
    ledger_index: int | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "recipient_id": self.recipient_id,
            "user_index": self.user_index,
            "tardos_score": round(self.tardos_score, 2),
            "tardos_threshold": round(self.tardos_threshold, 2),
            "score_ratio": round(self.score_ratio, 3),
            "crosses_threshold": self.crosses_threshold,
            "source": self.source,
            "ledger_index": self.ledger_index,
            "notes": self.notes,
        }


@dataclass
class Investigation:
    status: str
    doc_candidates: list[dict] = field(default_factory=list)
    doc_id: str | None = None
    doc_confidence: float = 0.0
    doc_ambiguous: bool = False
    pointer_index: int | None = None
    pointer_confidence: float = 0.0
    pointer_erasures: int = 0
    watermark_recovered: bool = False
    watermark_confidence: float = 0.0
    guarantee: str = "none"
    tardos_positions: int = 0
    tardos_required: int = 0
    candidates: list[Candidate] = field(default_factory=list)
    verification: dict | None = None
    ledger_sessions: list[dict] = field(default_factory=list)
    caveat: str = ATTRIBUTION_CAVEAT
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "document": {
                "doc_id": self.doc_id,
                "confidence": round(self.doc_confidence, 4),
                "ambiguous": self.doc_ambiguous,
                "candidates": self.doc_candidates,
            },
            "watermark": {
                "recovered": self.watermark_recovered,
                "confidence": round(self.watermark_confidence, 4),
                "ledger_index": self.pointer_index,
                "pointer_erasures": self.pointer_erasures,
                "tardos_positions": self.tardos_positions,
                "tardos_required": self.tardos_required,
                "tardos_guarantee": self.guarantee,
            },
            "candidates": [c.as_dict() for c in self.candidates],
            "verification": self.verification,
            "ledger_sessions": self.ledger_sessions,
            "notes": self.notes,
            "caveat": self.caveat,
        }


class Investigator:
    """Runs the pipeline against a deployment's ledger and corpus.

    ``ledger`` is anything exposing the read side of
    :class:`logfirst.ledger.log.LedgerLog` (``tree_size``, ``get_leaf``,
    ``inclusion_proof``, ``latest_sth``, ``sth_at``). It is never asked to
    *decide* anything -- every claim it provides is re-checked by ``evidence.py``
    before it reaches a result.
    """

    def __init__(self, docs: list[dict], ledger, log_pub: bytes,
                 witness_pubs: dict[str, bytes], recipient_pubs: dict[str, bytes],
                 tardos: TardosCode | None = None,
                 user_order: list[str] | None = None,
                 witness_quorum: int = 2, max_colluders: int = 2,
                 eps: float = 1e-3, top_k: int = 5):
        from .identify import DocumentIndex

        self.index = DocumentIndex(docs)
        self.docs = {d["doc_id"]: d for d in docs}
        self.ledger = ledger
        self.log_pub = log_pub
        self.witness_pubs = witness_pubs
        self.recipient_pubs = recipient_pubs
        self.tardos = tardos
        self.user_order = user_order or []
        self.witness_quorum = witness_quorum
        self.max_colluders = max_colluders
        self.eps = eps
        self.top_k = top_k
        self.n_users = len(self.user_order) or (tardos.n_users if tardos else 0)

    # -- ledger helpers ----------------------------------------------------

    def _seed_of(self, idx: int) -> bytes:
        """The watermark seed the authority bound to ledger entry ``idx``.

        Recomputed from the committed leaf rather than read from any server
        field, so it matches what was actually marked.
        """
        return watermark_seed(merkle.leaf_hash(self.ledger.get_leaf(idx)))

    def _sessions_for(self, doc_id: str) -> list[dict]:
        """Every decryption entry in the ledger for ``doc_id``.

        This is both the seed-search space and the fallback evidence path. It is
        deliberately a *list*: each row is a signed request a named recipient's
        key authorised, so each is a true statement that they decrypted the
        document -- and none of them says which copy was leaked.
        """
        out = []
        for idx in range(self.ledger.tree_size()):
            try:
                obj = evidence.parse_leaf(self.ledger.get_leaf(idx))
            except Exception:
                continue
            req = obj["request"]
            if req.get("doc_id") != doc_id:
                continue
            out.append({"ledger_index": idx, "recipient_id": req["recipient_id"],
                        "timestamp": req.get("timestamp"),
                        "device_fp": req.get("device_fp"),
                        "source_ip": obj.get("source_ip")})
        return out

    def _verify(self, idx: int) -> evidence.VerificationReport | None:
        """Re-check one ledger entry from public outputs alone.

        The head and the proof have to be taken at the *same* tree size, and
        that size is the entry's own commit size. Taking the head at the commit
        size and the proof over the current full tree -- which is what
        ``ledger.inclusion_proof`` returns -- folds the path against a tree the
        head does not describe, so inclusion fails for every entry except the
        newest. The failure is silent and one-directional: it reports *tampering*
        on honest entries, which is the worst way for this to be wrong. The
        bundle exporter takes both at the commit size for the same reason; see
        ``bundle._commit_size``, where that assumption is stated once.
        """
        try:
            leaf = self.ledger.get_leaf(idx)
        except IndexError:
            return None
        size = _commit_size(idx)
        sth = self.ledger.sth_at(size)
        if sth is None:
            # No witnessed head at the entry's own size: the append that should
            # have published one did not. Substituting the current head would
            # verify the leaf against a tree no witness ever attested to at this
            # size, so it is reported instead.
            rep = evidence.VerificationReport(index=idx)
            try:
                rep.kind = evidence.parse_leaf(leaf)["kind"]
            except Exception:
                pass
            rep.notes.append(
                f"no witnessed head at size {size}, the tree this entry was "
                "committed into; the entry cannot be verified against the head "
                "the witnesses actually co-signed")
            return rep
        try:
            proof = merkle.inclusion_proof(self.ledger.leaf_hashes()[:size], idx)
        except IndexError:
            return None
        try:
            req = evidence.request_from_leaf(leaf)
        except Exception:
            return None
        pub = self.recipient_pubs.get(req.recipient_id)
        if pub is None:
            rep = evidence.VerificationReport(index=idx,
                                              kind=evidence.KIND_DECRYPTION)
            rep.notes.append(f"no certificate on file for {req.recipient_id!r}; "
                             "the signature cannot be checked")
            return rep
        return evidence.verify_entry(idx, leaf, proof, sth, self.log_pub,
                                     self.witness_pubs, pub, self.witness_quorum)

    # -- the pipeline ------------------------------------------------------

    def investigate(self, leaked_text: str = "",
                    image_bytes: bytes | None = None) -> Investigation:
        # 1. Get text out of whatever we were handed.
        if image_bytes is not None:
            from ..watermark import ocr
            try:
                text = ocr.image_to_text(ocr.bytes_to_image(image_bytes))
            except Exception as exc:      # OCRError and PIL decode errors
                return Investigation(status=STATUS_EMPTY,
                                     notes=[f"could not read the image: {exc}"])
        else:
            text = leaked_text or ""
        if not text.strip():
            return Investigation(status=STATUS_EMPTY,
                                 notes=["no text to analyse"])

        # 2. Which document is this?
        cands = self.index.identify(text)
        if not cands:
            return Investigation(status=STATUS_UNIDENTIFIED,
                                 notes=["no candidate documents in the corpus"])
        from .identify import MIN_IDENTIFY_SCORE
        doc_candidates = [{"doc_id": c["doc_id"], "score": round(c["score"], 4)}
                          for c in cands]
        best = cands[0]
        if best["score"] < MIN_IDENTIFY_SCORE:
            return Investigation(
                status=STATUS_UNIDENTIFIED, doc_candidates=doc_candidates,
                doc_confidence=best["score"],
                notes=[f"best document match scored {best['score']:.3f}, below "
                       f"the {MIN_IDENTIFY_SCORE} floor; the fragment does not "
                       "look like it came from this corpus"])

        inv = Investigation(
            status=STATUS_NO_WATERMARK, doc_candidates=doc_candidates,
            doc_id=best["doc_id"], doc_confidence=best["score"],
            doc_ambiguous=len(cands) > 1)
        if inv.doc_ambiguous:
            inv.notes.append(
                "more than one document matches within the ambiguity margin; "
                "extraction was attempted against the best-scoring one. A wrong "
                "source document yields noise rather than a wrong name, so a "
                "failed decode below may mean the other candidate is the source.")

        doc = self.docs[best["doc_id"]]
        plan = payload.plan_for_document(linguistic.slot_count(doc["text"]),
                                         self.n_users, self.max_colluders,
                                         self.eps)
        inv.guarantee = plan["guarantee"]
        inv.tardos_positions = plan["tardos_bits"]
        inv.tardos_required = plan["tardos_required"]
        if not plan["ok"]:
            inv.notes.append(plan["reason"])
            return inv

        masked = plan["pointer_bits"]
        nbits = plan["total_bits"]
        mapping = align.align(doc["text"], text)
        coverage = align.coverage(doc["text"], mapping)
        if coverage < 0.35:
            inv.notes.append(
                f"only {coverage:.0%} of the canonical text could be aligned; "
                "the fragment may be too short or too heavily edited for "
                "reliable extraction")

        # 3. The candidate seeds: every session in which this document was
        #    decrypted. See the module docstring on why this search is sound.
        sessions = self._sessions_for(best["doc_id"])
        inv.ledger_sessions = sessions

        # 4. Tardos needs no seed, so read it once, independently.
        tardos_ranked: list[Candidate] = []
        if plan["tardos_bits"]:
            votes_raw, totals_raw = linguistic.extract(
                doc["text"], mapping, b"\x00" * 32, nbits, masked_bits=0)
            rec_raw = (votes_raw * 2 > totals_raw).astype(np.uint8)
            tardos_ranked = self._trace(
                rec_raw[plan["pointer_bits"]:plan["total_bits"]], plan,
                observed=totals_raw[plan["pointer_bits"]:plan["total_bits"]] > 0)

        # 5. Try each candidate seed for the pointer block.
        matched: tuple[int, float, int] | None = None
        # A pointer that decodes to an entry other than the one whose seed
        # produced it is a *structural* splice signal: no single recipient's mark
        # would do that. It is recorded here and used below, because it is
        # stronger evidence than any score -- the scores only say "two users look
        # elevated", this says "this copy was assembled from two marks".
        contradictory_pointer: int | None = None
        for s in sessions:
            idx = s["ledger_index"]
            try:
                seed = self._seed_of(idx)
            except IndexError:
                continue
            votes, totals = linguistic.extract(doc["text"], mapping, seed, nbits,
                                               masked_bits=masked)
            rec = (votes * 2 > totals).astype(np.uint8)
            ptr, conf, erasures = payload.decode_pointer(
                rec[:payload.POINTER_BITS], totals[:payload.POINTER_BITS])
            if ptr is None:
                continue
            if ptr == idx:
                # The seed from entry N recovered a watermark naming entry N.
                matched = (idx, conf, erasures)
                break
            # Decoded, but not to the entry this seed came from. Remember the
            # first such disagreement: it is the collusion / splice signal.
            if contradictory_pointer is None:
                contradictory_pointer = ptr
                inv.notes.append(
                    f"a pointer decoded to ledger index {ptr} while extracting "
                    f"under the seed for index {idx}; the copy may be spliced "
                    "from more than one recipient's version")

        if matched is None:
            # Whether this is a splice is a separate question from whether Tardos
            # could rank anyone, and answering it with "Tardos produced a
            # ranking" is wrong: the trace returns every user ranked, always, so
            # that test fires on any document long enough to carry Tardos
            # positions -- including an unmarked copy pasted straight from the
            # plaintext, which would then be reported as a suspected collusion
            # with named recipients. See ``tardos.classify_scores`` for the
            # measured rule and the two populations it separates.
            verdict = tardos_mod.NO_MARK
            if tardos_ranked:
                verdict = tardos_mod.classify_scores(
                    np.array([c.tardos_score for c in tardos_ranked]),
                    tardos_ranked[0].tardos_threshold)
            if contradictory_pointer is not None:
                # Structural evidence outranks any score: a pointer that decodes
                # to an entry other than the one whose seed recovered it cannot
                # come from a single recipient's mark.
                verdict = tardos_mod.COLLUSION

            inv.status = {
                tardos_mod.COLLUSION: STATUS_COLLUSION,
                tardos_mod.SINGLE_USER: STATUS_SINGLE_MARK,
                tardos_mod.NO_MARK: STATUS_NO_WATERMARK,
            }[verdict]
            inv.watermark_recovered = False
            inv.watermark_confidence = 0.0
            inv.notes.append(
                "the ledger pointer did not decode under any recorded session, "
                "so no single session can be named from this fragment")
            if inv.status == STATUS_COLLUSION:
                inv.candidates = tardos_ranked[:self.top_k]
                if contradictory_pointer is not None:
                    inv.notes.append(
                        "the pointer contradicted its own seed, which no single "
                        "recipient's mark can do; this copy was assembled from "
                        "more than one, so the candidates below are ranked by "
                        "the Tardos trace rather than named by a pointer")
                else:
                    inv.notes.append(
                        "the Tardos code is what still carries signal after a "
                        "splice; suspects below are ranked by that score alone")
            elif verdict == tardos_mod.SINGLE_USER and tardos_ranked:
                # One recipient's score clears the accusation threshold and
                # nobody else is near it -- a whole mark belonging to one person,
                # with a pointer that did not survive (heavy editing, truncation,
                # or a splice that resolved almost entirely one way). Not a
                # collusion, and not "no evidence" either: the candidate is
                # reported with its score, and the status is ``single-mark``
                # rather than ``no-watermark`` so that a caller reading only the
                # status is not told the opposite of what was found.
                inv.candidates = tardos_ranked[:self.top_k]
                inv.notes.append(
                    "one recipient's Tardos score clears the accusation "
                    "threshold while no other does, which is the shape of a "
                    "single mark rather than a mixture -- but the pointer did "
                    "not decode, so this is not an attribution; the candidate "
                    "below is reported with its score and nothing more")
            elif sessions:
                inv.notes.append(
                    f"fallback evidence only: the ledger records "
                    f"{len(sessions)} decryption(s) of this document. Any of "
                    "them could be the source; this list does not identify "
                    "which copy leaked.")
            self._annotate_guarantee(inv, plan)
            return inv

        idx, conf, erasures = matched
        inv.pointer_index = idx
        inv.watermark_recovered = True
        inv.watermark_confidence = conf
        inv.pointer_confidence = conf
        inv.pointer_erasures = erasures

        # 6. The watermark named a specific session. Verify that entry before
        #    believing any of it.
        rep = self._verify(idx)
        if rep is None:
            inv.status = STATUS_UNVERIFIED
            inv.notes.append(
                f"the pointer decoded to ledger index {idx}, but no entry there "
                "could be verified; no attribution is reported")
            return inv
        inv.verification = rep.as_dict()
        if not rep.verified:
            inv.status = STATUS_UNVERIFIED
            failed = [k for k in ("request_signature_ok", "inclusion_ok",
                                  "sth_signature_ok")
                      if not rep.as_dict()[k]]
            if not rep.witness_quorum_ok:
                failed.append("witness_quorum")
            if rep.witnesses_bad:
                failed.append("witness_signatures")
            inv.notes.append(
                "the pointed-to ledger entry FAILED verification ("
                + ", ".join(failed)
                + "). No attribution is reported: a pointer to an entry that "
                  "does not verify is evidence of tampering or of a forged "
                  "copy, not of who leaked it")
            return inv

        req = evidence.request_from_leaf(self.ledger.get_leaf(idx))
        inv.status = STATUS_ATTRIBUTED
        verified_cand = Candidate(
            recipient_id=req.recipient_id,
            user_index=(self.user_order.index(req.recipient_id)
                        if req.recipient_id in self.user_order else -1),
            tardos_score=0.0, tardos_threshold=0.0, score_ratio=0.0,
            crosses_threshold=True, source="ledger-pointer", ledger_index=idx,
            notes=["named by the watermark and confirmed by this recipient's own "
                   "signature in the ledger"])

        # 7. Merge in the Tardos ranking, marking where it agrees.
        if tardos_ranked:
            top = tardos_ranked[0]
            # The trace's own number for *this* candidate, whichever end of the
            # ranking they sit at. Left at zero it would display as "no
            # corroboration", which is a different statement from the true one.
            mine = next((c for c in tardos_ranked
                         if c.user_index == verified_cand.user_index), None)
            if mine is not None:
                verified_cand.tardos_score = mine.tardos_score
                verified_cand.tardos_threshold = mine.tardos_threshold
                verified_cand.score_ratio = mine.score_ratio
                # Reported as the Tardos channel sees it, even when that is
                # "does not cross". The pointer is an independent basis for this
                # candidate and `source` says so; overwriting the trace's verdict
                # with the pointer's authority would erase exactly the
                # disagreement an analyst needs to see.
                verified_cand.crosses_threshold = mine.crosses_threshold
            if top.user_index == verified_cand.user_index:
                verified_cand.notes.append(
                    "independently the highest-scoring Tardos suspect, so the "
                    "collusion-resistance channel agrees with the pointer")
            else:
                verified_cand.notes.append(
                    f"note: the Tardos channel's top suspect is "
                    f"{top.recipient_id!r} (score {top.tardos_score:.1f}), not "
                    "this candidate. That disagreement is itself a signal that "
                    "the copy may have been spliced from two recipients' "
                    "versions; both are reported")
            inv.candidates = ([verified_cand]
                              + [c for c in tardos_ranked
                                 if c.user_index != verified_cand.user_index
                                 ][:self.top_k])
        else:
            inv.candidates = [verified_cand]
        self._annotate_guarantee(inv, plan)
        return inv

    def _trace(self, tardos_bits: np.ndarray, plan: dict,
               observed: np.ndarray | None = None) -> list[Candidate]:
        """Rank every user by Tardos accusation score, best first.

        Returns all of them rather than the top ``k``: the caller needs to look
        up the score of a specific user -- the one the watermark pointer named --
        and a top-k list would leave that candidate with no score at all
        whenever the pointer and the trace disagree. A front end would then show
        ``0.0`` beside a name the watermark named, which reads as "no
        corroboration" when the truth is "the two channels disagree, and here is
        the trace's own number".

        ``observed`` marks the positions the extractor actually read. It is
        passed through to the scorer rather than defaulted, because scoring the
        unread remainder treats "nobody looked here" as the bit 0 -- see
        ``TardosCode.threshold`` for the measured size of that error.
        """
        if self.tardos is None or tardos_bits.size == 0:
            return []
        y = np.asarray(tardos_bits, dtype=np.uint8).ravel()
        # The code and the document's payload may not be the same length; score
        # over the overlap the document actually carried.
        m = min(len(y), self.tardos.m)
        if m == 0:
            return []
        obs = None
        if observed is not None:
            obs = np.asarray(observed, dtype=bool).ravel()[:m]
            if obs.size < m:
                # A mask shorter than the sequence would silently mask the tail
                # off; pad with True so the missing entries are scored rather
                # than dropped.
                obs = np.concatenate([obs, np.ones(m - obs.size, dtype=bool)])
        scores = self.tardos.scores(y[:m], observed=obs)
        # The threshold is scaled to the positions actually read, not to the
        # code's nominal length. See ``TardosCode.threshold``: comparing a
        # prefix's score against the full-length bar would put a real colluder
        # permanently out of reach, and counting unread positions would do the
        # same to the bar itself.
        m_read = int(obs.sum()) if obs is not None else m
        if m_read == 0:
            # The fragment did not reach the Tardos region at all -- the first
            # ``pointer_bits`` payload positions come first under the tiling, so
            # a short fragment is entirely pointer. There is no Tardos evidence
            # here, and returning a list of zeros would put every user in a
            # ranked table at 0.0 against a threshold of 0.0.
            return []
        Z = self.tardos.threshold(m_read)
        order = np.argsort(-scores)
        out = []
        for ui in order:
            ui = int(ui)
            rid = (self.user_order[ui] if ui < len(self.user_order)
                   else f"user-{ui}")
            out.append(Candidate(
                recipient_id=rid, user_index=ui,
                tardos_score=float(scores[ui]), tardos_threshold=float(Z),
                score_ratio=float(scores[ui] / Z) if Z else 0.0,
                crosses_threshold=bool(scores[ui] > Z), source="tardos-trace"))
        return out

    def _annotate_guarantee(self, inv: Investigation, plan: dict) -> None:
        if not plan["tardos_bits"]:
            return
        if plan["guarantee"] == "ranking-only":
            inv.notes.append(
                f"the Tardos code carried {plan['tardos_bits']} positions; the "
                f"formal false-accusation bound needs {plan['tardos_required']} "
                f"for {self.n_users} users against {self.max_colluders} "
                "colluders. Suspects are RANKED by score only -- the scores do "
                "not cross the accusation threshold at this code length, so no "
                "candidate here should be treated as a formal accusation.")
