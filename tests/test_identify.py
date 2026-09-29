"""Document identification, and the floor that decides when to give up.

Identification runs first in the leak-check pipeline, and everything downstream
depends on it: extraction works by differencing the leaked text against a
canonical document's *own* carrier slot positions, so identifying the wrong
document does not produce an error -- it produces bits. The bits are noise, the
pointer fails to decode, and the pipeline reports "no attribution", which is the
right outcome reached by luck. The floor in ``MIN_IDENTIFY_SCORE`` is what makes
it a decision rather than luck.

That floor was originally 0.05, and it was wrong. TF-IDF cosine over word
n-grams is never near zero for English prose, because ordinary words occur in the
corpus as well, so a threshold chosen by intuition sits *below* the entire
out-of-corpus band and can never fire. The measurements below are what fixed it,
and they are reproduced here as tests so the constant can be re-derived rather
than trusted:

    out-of-corpus, 300 chunks of 150-400 words   0.063 - 0.201
    in-corpus,  30 words                         0.307 - ...   (79% correct)
    in-corpus,  60 words                         0.412 - ...   (99% correct)
    in-corpus, 100 words                         0.507 - ...   (99% correct)
    in-corpus, 200 words                         0.636 - ...   (100% correct)

``MIN_IDENTIFY_SCORE`` is set to 0.25, which is above every out-of-corpus sample
measured and below every in-corpus one. The tests assert the *separation* rather
than the constant, so a change to the vectoriser that collapsed the two bands
would fail here instead of silently turning the guard into decoration.

The out-of-corpus pool is deliberately this repository's own docstrings: prose
written by the same author, on the same subject matter, in the same register as
the corpus documents. A pool of unrelated text (poetry, SQL, source code) makes
the separation look far better than it is, and would justify a threshold that
does not survive contact with a genuinely wrong paste.
"""

from __future__ import annotations

import ast
import glob
import random
from pathlib import Path

import pytest

from logfirst.data import corpus
from logfirst.forensics.identify import MIN_IDENTIFY_SCORE, DocumentIndex

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def index() -> DocumentIndex:
    return DocumentIndex(corpus.make_document_set(8, seed=7, target_words=1200))


@pytest.fixture(scope="module")
def out_of_corpus() -> list[str]:
    """Prose that is emphatically not from the corpus, but is the same language.

    Taken from this repository's own docstrings -- see the module docstring for
    why the choice of pool is the difference between a real calibration and a
    flattering one.
    """
    chunks: list[str] = []
    paths = sorted(glob.glob(str(REPO / "logfirst" / "**" / "*.py"),
                             recursive=True))
    paths += sorted(glob.glob(str(REPO / "tests" / "*.py")))
    for path in paths:
        try:
            tree = ast.parse(Path(path).read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            doc = ast.get_docstring(node)
            if doc and len(doc.split()) > 40:
                chunks.append(" ".join(doc.split()))
    assert len(chunks) > 50, "the out-of-corpus pool is too small to calibrate on"
    return chunks


def fragment(text: str, n_words: int, rng: random.Random) -> str:
    toks = text.split()
    start = rng.randrange(0, max(1, len(toks) - n_words))
    return " ".join(toks[start:start + n_words])


# ==========================================================================
# What identification has to get right
# ==========================================================================

def test_a_whole_document_matches_itself(index):
    for doc in index.docs:
        best = index.identify(doc["text"])[0]
        assert best["doc_id"] == doc["doc_id"]
        assert best["score"] == pytest.approx(1.0, abs=1e-6)


def test_a_fragment_identifies_its_source_document(index):
    """The ordinary case: a paragraph pasted out of one document."""
    rng = random.Random(11)
    for n in (400, 200, 100, 60):
        hits = 0
        for trial in range(40):
            doc = index.docs[trial % len(index.docs)]
            got = index.identify(fragment(doc["text"], n, rng))[0]
            hits += got["doc_id"] == doc["doc_id"]
        assert hits == 40, f"only {hits}/40 {n}-word fragments identified rightly"


def test_identification_survives_word_level_damage(index):
    """OCR does not return the words that were printed.

    A fragment whose carrier words have been swapped for their synonyms -- which
    is exactly what a marked copy looks like -- must still identify, or the
    pipeline could never read its own watermarks.
    """
    from logfirst.watermark import linguistic

    rng = random.Random(12)
    doc = index.docs[0]
    marked, _ = linguistic.embed(doc["text"], _payload(3), b"\x5a" * 32,
                                 masked_bits=40)
    assert marked != doc["text"]
    for n in (400, 200, 100):
        got = index.identify(fragment(marked, n, rng))[0]
        assert got["doc_id"] == doc["doc_id"]


def _payload(index_: int):
    from logfirst.watermark import payload
    return payload.build_payload(index_)


def test_a_short_fragment_is_reported_as_ambiguous_rather_than_guessed(index):
    """When the top two candidates are close, both come back.

    Picking the higher one silently would let a fragment that genuinely straddles
    two documents produce a single confident-looking answer. The corpus documents
    share a register and a vocabulary, so short fragments really are ambiguous,
    and the caller is told so via a longer candidate list.
    """
    rng = random.Random(13)
    multi = 0
    for trial in range(40):
        doc = index.docs[trial % len(index.docs)]
        cands = index.identify(fragment(doc["text"], 30, rng))
        multi += len(cands) > 1
    assert multi > 10, (
        "30-word fragments from a homogeneous corpus were always unambiguous; "
        "either the corpus is unrealistically distinctive or the ambiguity "
        "margin is not being applied")


def test_the_ambiguity_margin_is_what_controls_the_candidate_list(index):
    rng = random.Random(14)
    frag = fragment(index.docs[0]["text"], 60, rng)
    assert len(index.identify(frag, ambiguity_margin=0.0)) == 1
    assert len(index.identify(frag, ambiguity_margin=0.9)) >= 2


def test_candidates_are_returned_best_first(index):
    rng = random.Random(15)
    cands = index.identify(fragment(index.docs[0]["text"], 80, rng), top_k=5)
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
    assert all(c["doc_id"] in index.ids for c in cands)


# ==========================================================================
# The floor: the separation between "in the corpus" and "not in the corpus"
# ==========================================================================

def test_out_of_corpus_text_never_clears_the_floor(index, out_of_corpus):
    """The guard can only work if it is above the band it is guarding against.

    This is the assertion the old value of 0.05 would have failed: unrelated
    prose scores up to 0.20, so a floor of 0.05 labelled every wrong paste as a
    document match and sent the pipeline off to difference it against a
    canonical text it had nothing to do with.
    """
    rng = random.Random(16)
    scores = []
    for trial in range(200):
        chunk = out_of_corpus[trial % len(out_of_corpus)]
        n = (150, 250, 400)[trial % 3]
        scores.append(index.identify(fragment(chunk, n, rng))[0]["score"])

    worst = max(scores)
    assert worst < MIN_IDENTIFY_SCORE, (
        f"out-of-corpus text scored {worst:.4f}, at or above the "
        f"{MIN_IDENTIFY_SCORE} floor; the 'unidentified' path would never fire")


def test_in_corpus_fragments_clear_the_floor_from_thirty_words_up(index):
    """The other side of the gap: the floor must not reject real fragments.

    Thirty words is the shortest fragment the pipeline can do anything useful
    with, so that is where the floor has to stop being an obstacle.
    """
    rng = random.Random(17)
    for n in (30, 60, 100, 200):
        worst = min(index.identify(fragment(
            index.docs[trial % len(index.docs)]["text"], n, rng))[0]["score"]
            for trial in range(60))
        assert worst > MIN_IDENTIFY_SCORE, (
            f"{n}-word in-corpus fragments score down to {worst:.4f}, below the "
            f"{MIN_IDENTIFY_SCORE} floor")


def test_the_two_bands_do_not_overlap(index, out_of_corpus):
    """The floor sits in a real gap, stated as an explicit margin.

    A floor that merely happened to be between two sampled extremes would break
    on the next corpus. This asserts the gap is wide -- the best out-of-corpus
    sample is well clear of the worst 60-word in-corpus one -- so the constant
    can be re-derived from the measurement rather than tuned to it.
    """
    rng = random.Random(18)
    oob = max(index.identify(fragment(out_of_corpus[t % len(out_of_corpus)],
                                     (200, 400)[t % 2], rng))[0]["score"]
              for t in range(120))
    inb = min(index.identify(fragment(
        index.docs[t % len(index.docs)]["text"], 60, rng))[0]["score"]
        for t in range(120))

    assert inb > oob, (
        f"the bands overlap: out-of-corpus reaches {oob:.4f}, in-corpus starts "
        f"at {inb:.4f}")
    assert MIN_IDENTIFY_SCORE > oob and MIN_IDENTIFY_SCORE < inb
    # ...with room on both sides, so a corpus shift does not flip a sample.
    assert (inb - oob) > 0.05


def test_the_floor_is_reported_not_applied_silently(index, out_of_corpus):
    """A score below the floor must remain visible to the caller.

    ``identify`` returns the ranked list either way; deciding what to do about a
    low score belongs to the pipeline, which reports the number. If the floor
    were applied inside ``identify`` the analyst would see an empty result and
    no way to tell "wrong corpus" from "nothing matched at all".
    """
    rng = random.Random(19)
    cands = index.identify(fragment(out_of_corpus[0], 200, rng))
    assert cands, "identify returned nothing at all for out-of-corpus text"
    assert cands[0]["score"] < MIN_IDENTIFY_SCORE
