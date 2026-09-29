"""The collusion indicator, re-measured rather than trusted.

``tardos.MARK_PRESENT`` and ``tardos.USER_ELEVATED`` decide whether a fragment is
reported as a collusion, as one person's mark, or as carrying no mark at all. They
are measured constants, and a measured constant with nothing re-measuring it is
just an assumption with a comment attached: change the corpus, the document
length, the code length or the user count and the separation they encode can
vanish while the numbers sit there looking authoritative.

So this file re-runs the measurement. It is slower than the rest of the suite --
it opens real documents and runs real traces -- deliberately, because the thing
being tested is an empirical claim about how populations of scores are separated,
and the only honest way to test that is to produce the populations.

Three populations, in the order of how bad it would be to get them wrong:

* **no mark** -- an unmarked copy of the plaintext, or a fragment too short to
  reach the Tardos region. Reporting these as a collusion would name recipients
  on the strength of noise.
* **one user's mark** -- a single recipient's marked copy. Reporting this as a
  collusion would accuse one person of conspiring with themself.
* **a splice** -- two recipients' copies mixed under the marking assumption. The
  two colluders must rank first and second.

The bounds asserted below are the ones the constants were chosen from, with the
sample sizes recorded rather than implied.
"""

from __future__ import annotations

import numpy as np
import pytest

from logfirst.data.scenario import Scenario
from logfirst.forensics import align
from logfirst.watermark import linguistic, payload, tardos

DOC = "DOC-0000"
SPLICE_ROUNDS = 8


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("collusion")
    sc = Scenario.build(str(root / "data"), n_docs=1, target_words=1800, seed=5,
                        start_witnesses=True, min_witnesses=2)
    users = list(sc.dep.tardos_config()["users"])
    sc.authority.seal(sc.doc(DOC)["text"], DOC, "SECRET", users)
    try:
        yield sc, users
    finally:
        sc.close()


def _scores(sc, text: str) -> tuple[np.ndarray, float]:
    """The Tardos score vector and threshold for a fragment, as the pipeline reads it.

    Mirrors ``Investigator``'s extraction exactly, including the ``observed``
    mask: the Tardos region needs no seed, so it is read once with a zero seed
    and without the pointer mask, and only the positions the extractor actually
    read are scored. Dropping the mask here would make this file measure a
    different quantity from the one the pipeline acts on -- which is how the
    unobserved-position bug stayed invisible.
    """
    inv = sc.investigator()
    users = sc.dep.tardos_config()["users"]
    doc_text = sc.doc(DOC)["text"]
    plan = payload.plan_for_document(linguistic.slot_count(doc_text),
                                     len(users), inv.max_colluders, inv.eps)
    mapping = align.align(doc_text, text)
    votes, totals = linguistic.extract(doc_text, mapping, b"\x00" * 32,
                                       plan["total_bits"], masked_bits=0)
    sl = slice(plan["pointer_bits"], plan["total_bits"])
    rec = (votes * 2 > totals).astype(np.uint8)
    ranked = inv._trace(rec[sl], plan, observed=totals[sl] > 0)
    scores = np.zeros(len(users))
    for c in ranked:
        scores[c.user_index] = c.tardos_score
    z = ranked[0].tardos_threshold if ranked else 0.0
    return scores, z


def _verdict(sc, text):
    scores, z = _scores(sc, text)
    return tardos.classify_scores(scores, z), scores, z


def test_nothing_without_a_mark_is_called_a_collusion(world):
    """The false-positive side, and the one that names innocent people.

    An unmarked copy of the plaintext carries no fingerprint at all. Reporting it
    as a suspected collusion would put named recipients in a report on the
    strength of noise -- which is exactly what the rule did before this was
    measured, because it asked whether the trace had produced a ranking rather
    than whether that ranking meant anything.
    """
    sc, users = world
    verdict, scores, z = _verdict(sc, sc.doc(DOC)["text"])
    assert verdict == tardos.NO_MARK, (
        f"an unmarked copy of the plaintext was classified {verdict!r}: "
        f"scores/Z = {np.round(scores / z, 2).tolist()}")


def test_a_fragment_too_short_for_the_region_yields_no_tardos_evidence(world):
    """The first payload positions are the pointer, so a short fragment is all pointer.

    Nothing about Tardos can be said from it, and saying "every user scored 0.0
    against a threshold of 0.0" would be worse than saying nothing.
    """
    sc, users = world
    marked = sc.node(users[0]).open(DOC, mark=True)["marked_text"]
    short = " ".join(marked.split()[:90])
    scores, z = _scores(sc, short)
    assert z == 0.0, (
        "a 90-word fragment should not reach the Tardos region; got a "
        f"threshold of {z}")
    assert scores.max() == 0.0
    assert tardos.classify_scores(scores, z) == tardos.NO_MARK


def test_a_whole_marked_copy_is_one_user_not_a_collusion(world):
    """A single recipient's own copy, if the pointer were lost.

    The pointer normally catches this and attributes it, so this branch is only
    reached when the pointer failed -- but the trace must still not read one
    person's mark as a conspiracy, and must not accuse them of colluding with
    themself.
    """
    sc, users = world
    for r in users:
        marked = sc.node(r).open(DOC, mark=True)["marked_text"]
        verdict, scores, z = _verdict(sc, marked)
        assert verdict == tardos.SINGLE_USER, (
            f"{r}'s own marked copy was classified {verdict!r}: scores/Z = "
            f"{np.round(scores / z, 2).tolist()}")
        # And the one elevated user is the person whose copy it is.
        assert users[int(np.argmax(scores))] == r, (
            "the highest-scoring user is not the recipient whose copy this is")


def test_a_splice_is_classified_as_a_collusion(world):
    """Every real splice, and the colluders must be the top two.

    A splice is decided only at positions where the two codewords differ, and the
    arcsine bias puts most positions near p=0 or p=1, where two users usually
    share a bit -- so a splice can resolve almost entirely in one colluder's
    favour and leave the other in the noise. Those lopsided cases are classified
    as one user's mark rather than as a collusion, deliberately, because from the
    score vector alone they are not separable from a fragment of a single copy.
    What must hold in every case is that the top-ranked user is a real colluder.
    """
    sc, users = world
    lopsided = 0
    for i in range(SPLICE_ROUNDS):
        a = users[i % len(users)]
        b = users[(i + 1) % len(users)]
        spliced = sc.leak_collusion(a, b, DOC, seed=100 + i)["leaked_text"]
        verdict, scores, z = _verdict(sc, spliced)
        order = [users[int(ui)] for ui in np.argsort(-scores)]

        assert verdict != tardos.NO_MARK, (
            f"a real splice of {a}+{b} was reported as carrying no mark: "
            f"scores/Z = {np.round(scores / z, 2).tolist()}")
        assert order[0] in (a, b), (
            f"the top-ranked user for a splice of {a}+{b} was {order[0]}, who "
            f"is not a colluder; ranking was {order}")

        if verdict == tardos.SINGLE_USER:
            lopsided += 1
        else:
            assert set(order[:2]) == {a, b}, (
                f"a splice of {a}+{b} was called a collusion but the two "
                f"colluders are not the top two; ranking was {order}")
    assert lopsided < SPLICE_ROUNDS, (
        "every splice in this sample lifted both colluders, so this test is not "
        "exercising the lopsided case it exists for -- widen the sample")


def test_the_cuts_sit_between_the_measured_populations(world):
    """The constant-level claim, asserted once, with the sample sizes named.

    The per-case tests above are the real coverage; this is the summary they add
    up to, so a drift of a population across a cut shows up as one failure with
    the numbers attached rather than as a puzzling misclassification elsewhere.
    """
    sc, users = world
    doc_text = sc.doc(DOC)["text"]

    plain_scores, plain_z = _scores(sc, doc_text)
    assert plain_z > 0, "the plaintext should reach the Tardos region"
    unmarked_plain = float(plain_scores.max() / plain_z)
    splice_tops = []
    for i in range(SPLICE_ROUNDS):
        a = users[i % len(users)]
        b = users[(i + 1) % len(users)]
        spliced = sc.leak_collusion(a, b, DOC, seed=300 + i)["leaked_text"]
        scores, z = _scores(sc, spliced)
        splice_tops.append(float(scores.max()) / z)

    assert unmarked_plain < tardos.MARK_PRESENT < min(splice_tops), (
        f"the 'a mark is present' cut ({tardos.MARK_PRESENT}) no longer sits "
        f"between the populations: unmarked plaintext top {unmarked_plain:.2f}, "
        f"best splice top {min(splice_tops):.2f}. Re-measure and update "
        f"logfirst/watermark/tardos.py and the README table together.")


def test_unread_positions_are_not_scored(world):
    """The bug this file was written alongside.

    A fragment leaves most payload positions unread, and the extractor reports
    those with ``totals == 0``. Converting that to a hard bit 0 and summing it
    scores positions nobody looked at -- measured, a seven-tenths fragment of a
    recipient's own marked copy reached 1.28 Z that way, *above* the whole copy,
    because the unread remainder defaulted to bits that happened to suit that
    codeword.

    The check is that the score of a prefix is never higher than the score of the
    whole: partial evidence cannot be stronger than complete evidence.
    """
    sc, users = world
    marked = sc.node(users[0]).open(DOC, mark=True)["marked_text"]
    words = marked.split()

    whole, z_whole = _scores(sc, marked)
    assert z_whole > 0
    top_whole = whole.max() / z_whole

    for frac in (0.35, 0.7):
        part = " ".join(words[:int(len(words) * frac)])
        scores, z = _scores(sc, part)
        if z == 0:
            continue                    # did not reach the region; nothing claimed
        top = scores.max() / z
        assert top <= top_whole + 1e-9, (
            f"a {frac:.0%} fragment of a marked copy scored {top:.2f} Z against "
            f"the whole copy's {top_whole:.2f} Z -- partial evidence cannot be "
            f"stronger than the complete evidence it is a part of")


def test_a_zero_threshold_is_not_a_collusion():
    """No Tardos positions means no evidence from this channel, not guilt.

    Guarded because ``z <= 0`` divides by zero in the naive implementation and
    because a caller that reached here with no positions has nothing to report.
    """
    assert tardos.classify_scores(np.zeros(4), 0.0) == tardos.NO_MARK
    assert tardos.classify_scores(np.array([]), 10.0) == tardos.NO_MARK
    assert tardos.colluders_above(np.zeros(4), 0.0) == 0


def test_masking_is_per_position_not_a_prefix():
    """The mask selects columns, rather than truncating the sequence.

    A fragment's unread positions are scattered through the payload -- the tiling
    repeats the payload across the document -- so masking has to drop the
    positions in the middle as well as at the end. Scoring a prefix instead would
    silently attribute the fragment's evidence to the wrong payload positions.
    """
    rng = np.random.default_rng(0)
    n_users, m = 4, 64
    codewords = rng.integers(0, 2, size=(n_users, m)).astype(np.uint8)
    code = tardos.TardosCode(codewords=codewords, p=np.full(m, 0.5), c=2,
                             eps=0.01)
    y = rng.integers(0, 2, size=m).astype(np.uint8)

    # Keep the first 8 and the last 8 positions only.
    keep = np.zeros(m, dtype=bool)
    keep[:8] = keep[-8:] = True

    # At p=0.5 both contributions are 1, so a position's contribution for user i
    # is exactly (2y-1)(2x-1): +1 when the codeword bit matches the observed bit
    # and -1 when it does not. Summing that over the *kept* columns is what the
    # mask must produce; summing it over the whole row is what scoring the
    # unread middle would add.
    sign = (2 * y.astype(np.int64) - 1)
    contribution = sign * (2 * codewords.astype(np.int64) - 1)
    expected = contribution[:, keep].sum(axis=1).astype(float)

    masked = code.scores(y, observed=keep)
    assert np.allclose(masked, expected), (
        f"masking did not select the kept positions: got {masked}, expected "
        f"{expected}")

    # And the dropped middle really would have changed the answer, so the test
    # is not passing because the mask happens to be a no-op.
    assert not np.allclose(code.scores(y), masked), (
        "keeping the first and last eighths produced the same score as reading "
        "everything, so this input cannot detect the difference")

    # An all-true mask is the same as no mask at all, which is what a whole
    # document supplies.
    assert np.allclose(code.scores(y, observed=np.ones(m, dtype=bool)),
                       code.scores(y))
